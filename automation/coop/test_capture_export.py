"""Trajectory continuity must survive chunk rotation without inventing game endings."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orebit_rl"))
from capture_export import Chunk, ExportError, assemble
from test_capture import records


def trajectory_chunk(index, sequence, session="a" * 32, terminal=False):
    manifest, transition = records(session, index)
    transition["sequence"] = sequence
    transition["tick"] = sequence
    transition["next_tick"] = sequence + 1
    transition["observation"]["state"][0] = sequence
    transition["next_observation"]["state"][0] = sequence + 1
    transition.update(terminated=terminal, reason="death" if terminal else "running")
    manifest["checkpoint"] = {"sequence": sequence, "tick": sequence,
                              "observation": copy.deepcopy(transition["observation"])}
    return Chunk(Path(f"/{session}/{index:08d}.jsonl.gz"), manifest, [transition], "f" * 64)


class CaptureExportBoundaryTest(unittest.TestCase):
    def test_capability_renewal_keeps_one_contiguous_episode(self):
        chunks = [trajectory_chunk(0, 0), trajectory_chunk(1, 1, "b" * 32, terminal=True)]
        segment, = assemble(chunks, allow_incomplete=False)
        self.assertEqual([t["sequence"] for t in segment.transitions], [0, 1])
        self.assertEqual([t["terminated"] for t in segment.transitions], [False, True])
        self.assertEqual([source[2] for source in segment.sources], ["a" * 32, "b" * 32])
        self.assertEqual(segment.transitions[0]["next_observation"], segment.transitions[1]["observation"])
        self.assertFalse(segment.incomplete)

    def test_missing_chunk_is_rejected_or_split_without_a_fabricated_end(self):
        chunks = [trajectory_chunk(0, 0), trajectory_chunk(2, 2, terminal=True)]
        with self.assertRaises(ExportError):
            assemble(chunks, allow_incomplete=False)
        first, second = assemble(chunks, allow_incomplete=True)
        self.assertEqual([t["sequence"] for t in first.transitions], [0])
        self.assertEqual([t["sequence"] for t in second.transitions], [2])
        self.assertFalse(first.transitions[-1]["terminated"])
        self.assertFalse(first.transitions[-1]["truncated"])
        self.assertTrue(second.transitions[-1]["terminated"])
        self.assertIn("missing_chunks", first.incomplete)
        self.assertIn("missing_episode_start", second.incomplete)

    def test_adjacent_state_discontinuity_is_not_a_permissible_capture_gap(self):
        chunks = [trajectory_chunk(0, 0), trajectory_chunk(1, 1, terminal=True)]
        chunks[1].transitions[0]["observation"]["state"][0] = 9
        chunks[1].manifest["checkpoint"]["observation"]["state"][0] = 9
        with self.assertRaises(ExportError):
            assemble(chunks, allow_incomplete=True)

    def test_human_and_replay_provenance_never_mix(self):
        chunks = [trajectory_chunk(0, 0), trajectory_chunk(1, 1, terminal=True)]
        chunks[1].manifest["actor"] = "replay"
        with self.assertRaises(ExportError):
            assemble(chunks, allow_incomplete=True)

    def test_episode_cannot_continue_after_a_true_terminal(self):
        chunks = [trajectory_chunk(0, 0, terminal=True), trajectory_chunk(1, 1, terminal=True)]
        with self.assertRaises(ExportError):
            assemble(chunks, allow_incomplete=True)


if __name__ == "__main__":
    unittest.main()
