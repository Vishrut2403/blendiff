"""
tests/test_geometry_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Storing vertex positions so a snapshot can be returned to.

Snapshots record a digest of a mesh, which answers "did this change" and
cannot answer "put it back". Stored positions answer the second question, at
a cost measured on a two million vertex mesh:

    plain JSON                   62.0 MB
    zlib + base64, float32       20.0 MB
    zlib + base64, quantised     15.0 MB

Quantising to the grid the digests already use is free, and compresses well
because neighbouring vertices share high-order bytes.
"""

import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.extractor.geometry_store import (
	FORMAT,
	decode_positions,
	encode_positions,
	is_stored_geometry,
)


class TestRoundTrip:

	def test_positions_come_back_unchanged(self):
		source = [1.5, -2.25, 0.0, 100.125, -0.000001, 3.75]
		assert decode_positions(encode_positions(source)) == pytest.approx(source)

	def test_a_large_mesh_round_trips(self):
		random.seed(7)
		source = [round(random.uniform(-50, 50), 6) for _ in range(30_000)]
		back = decode_positions(encode_positions(source))
		assert len(back) == len(source)
		assert back == pytest.approx(source, abs=1e-6)

	def test_an_empty_sequence_round_trips(self):
		assert decode_positions(encode_positions([])) == []

	def test_precision_matches_the_digest_grid(self):
		# Coordinates are already rounded to six places for hashing, so
		# storing them at that grid loses nothing the digests kept.
		source = [0.1234564999, 0.1234565001]
		back = decode_positions(encode_positions(source))
		assert all(abs(v - round(v, 6)) < 1e-9 for v in back)

	def test_it_is_smaller_than_json(self):
		"""
		At least half the size, and far better than that at real scale.

		Ten thousand vertices of random noise compresses about 2.2x. A real
		two million vertex mesh measured 62 MB as JSON against 15 MB stored,
		roughly 4x, because zlib has more to work with and neighbouring
		vertices in an actual mesh share high-order bytes. The floor here is
		the pessimistic case, not the expected one.
		"""
		import json

		random.seed(11)
		source = [round(random.uniform(-10, 10), 6) for _ in range(30_000)]
		packed = len(encode_positions(source))
		as_json = len(json.dumps(source))
		assert packed < as_json / 2, f"{packed} vs {as_json}"


class TestItRefusesRatherThanGuesses:
	"""Half a mesh written into a scene is worse than a refusal."""

	@pytest.mark.parametrize("value", ["", "nope", "q9:abcd", "q1:!!!!", None, 42, []])
	def test_unreadable_input_raises(self, value):
		with pytest.raises(ValueError):
			decode_positions(value)

	def test_a_future_format_is_named_in_the_error(self):
		with pytest.raises(ValueError, match="q9"):
			decode_positions("q9:" + "A" * 8)

	def test_truncated_data_is_refused(self):
		import base64, zlib

		# Three bytes cannot be a whole 4-byte integer.
		blob = base64.b64encode(zlib.compress(b"abc")).decode("ascii")
		with pytest.raises(ValueError, match="truncated"):
			decode_positions(f"{FORMAT}:{blob}")


class TestRecognisingStoredGeometry:

	def test_it_recognises_its_own_output(self):
		assert is_stored_geometry(encode_positions([1.0, 2.0, 3.0]))

	def test_a_digest_is_not_stored_geometry(self):
		# Digests are "2:<hex>". Confusing the two handed a hash to the
		# decoder once already.
		assert not is_stored_geometry("2:40d15928362d4640ef2cdcd20542fa75")

	@pytest.mark.parametrize("value", ["", None, 5, [], "q2:abc"])
	def test_anything_else_is_not(self, value):
		assert not is_stored_geometry(value)
