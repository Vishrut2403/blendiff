"""
tests/test_coerce.py
~~~~~~~~~~~~~~~~~~~~~
Turning Blender values into JSON-safe Python.

The bug these lock down: three extractors guarded conversion with
`hasattr(val, "__iter__")`, which is False for every mathutils type because
they implement the old sequence protocol instead. A Vector therefore passed
through unconverted and json.dumps rejected the whole snapshot, so capture
produced nothing at all. An Array modifier with a relative offset was enough.

Every fixture in this suite built modifiers from plain floats, which is why it
took a real .blend to surface it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.extractor.coerce import is_jsonable, to_jsonable


class SequenceOnly:
    """
    Stands in for mathutils types: len() and indexing, but no __iter__.

    This is the exact shape that defeated the old guard.
    """

    def __init__(self, values):
        self._values = list(values)

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


class Unconvertible:
    """Neither scalar nor sequence, like an opaque bpy struct."""

    def __repr__(self):
        return "<opaque>"


class TestTheOriginalBug:
    def test_the_old_guard_would_have_missed_this(self):
        """Documents why hasattr was the wrong question to ask."""
        assert not hasattr(SequenceOnly([1.0, 2.0]), "__iter__")

    def test_sequence_without_iter_is_converted(self):
        assert to_jsonable(SequenceOnly([0.0, 0.0, -1.38])) == [0.0, 0.0, -1.38]

    def test_converted_value_is_json_serializable(self):
        value = to_jsonable(SequenceOnly([0.0, 0.0, -1.38]))
        assert json.dumps(value) == "[0.0, 0.0, -1.38]"

    def test_nested_sequences_convert(self):
        """A Matrix is a sequence of rows."""
        matrix = SequenceOnly([SequenceOnly([1.0, 0.0]), SequenceOnly([0.0, 1.0])])
        assert to_jsonable(matrix) == [[1.0, 0.0], [0.0, 1.0]]


class TestScalars:
    def test_scalars_pass_through(self):
        for value in (1, 1.5, True, "text", None):
            assert to_jsonable(value) == value

    def test_string_is_not_treated_as_a_sequence(self):
        assert to_jsonable("abc") == "abc"

    def test_bool_survives_as_bool(self):
        assert to_jsonable(True) is True


class TestContainers:
    def test_list_is_converted_elementwise(self):
        assert to_jsonable([SequenceOnly([1.0]), 2]) == [[1.0], 2]

    def test_dict_values_are_converted(self):
        assert to_jsonable({"offset": SequenceOnly([1.0, 2.0])}) == {"offset": [1.0, 2.0]}

    def test_dict_keys_become_strings(self):
        assert to_jsonable({1: "a"}) == {"1": "a"}

    def test_tuple_becomes_list(self):
        assert to_jsonable((1, 2)) == [1, 2]

    def test_empty_containers(self):
        assert to_jsonable([]) == [] and to_jsonable({}) == {}


class TestFallbacks:
    def test_unconvertible_becomes_its_string(self):
        """
        Losing fidelity on one exotic field beats failing the whole snapshot,
        which is what the original bug did.
        """
        assert to_jsonable(Unconvertible()) == "<opaque>"

    def test_deep_nesting_stops_rather_than_recursing_forever(self):
        node = SequenceOnly([1.0])
        for _ in range(20):
            node = SequenceOnly([node])
        result = to_jsonable(node)
        assert json.dumps(result)  # must not raise

    def test_self_referencing_list_does_not_hang(self):
        loop = [1]
        loop.append(loop)
        assert json.dumps(to_jsonable(loop))


class TestIsJsonable:
    def test_scalars_are_jsonable(self):
        assert all(is_jsonable(v) for v in (1, 1.5, True, "s", None))

    def test_raw_sequence_type_is_not(self):
        assert not is_jsonable(SequenceOnly([1.0]))

    def test_converted_value_is(self):
        assert is_jsonable(to_jsonable(SequenceOnly([1.0])))

    def test_nested_bad_value_is_detected(self):
        assert not is_jsonable({"a": [1, SequenceOnly([2.0])]})

    def test_non_string_key_is_not_jsonable(self):
        assert not is_jsonable({1: "a"})
