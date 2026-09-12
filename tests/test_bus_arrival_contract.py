"""公車即時到站的正確性契約。

重點：同名／相似站牌不得回傳「看似合理但錯誤」的答案。
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402


def _stop(stop_id, name, direction=0, eta=120):
    return {
        "StopID": stop_id,
        "StopName": {"Zh_tw": name},
        "Direction": direction,
        "EstimateTime": eta,
        "StopStatus": 0,
        "PlateNumb": "",
    }


SAMPLE = [
    _stop("S1", "中山國小", direction=0),
    _stop("S2", "中山國中", direction=0),
    _stop("S3", "台北車站", direction=0),
    _stop("S4", "台北車站", direction=1),
]


def _run(**kwargs):
    params = server.BusArrivalInput(city="台北", route_name="299", **kwargs)
    with patch.object(server, "_tdx_get", return_value=SAMPLE) as tdx:
        async def _fake(*_a, **_k):
            return SAMPLE
        tdx.side_effect = _fake
        return asyncio.run(server.tdx_get_bus_arrival(params))


class BusArrivalContractTests(unittest.TestCase):
    def test_ambiguous_stop_name_returns_candidates_not_a_guess(self) -> None:
        """「中山」同時命中中山國小與中山國中，必須回候選清單而非任選一個。"""
        result = _run(stop_name="中山")

        self.assertIn("多個站牌", result)
        self.assertIn("S1", result)
        self.assertIn("S2", result)
        # 不可直接給出到站時間，那代表它已經替使用者選了一個
        self.assertNotIn("約 2 分鐘", result)

    def test_exact_name_match_wins_over_substring(self) -> None:
        """完全相同的站名應直接採用，不應因為是子字串就進入候選流程。"""
        result = _run(stop_name="台北車站")

        self.assertNotIn("多個站牌", result)
        self.assertIn("台北車站", result)

    def test_stop_id_pins_a_single_stop(self) -> None:
        result = _run(stop_id="S2")

        self.assertIn("中山國中", result)
        self.assertNotIn("中山國小", result)

    def test_unknown_stop_id_is_reported(self) -> None:
        result = _run(stop_id="NOPE")

        self.assertIn("找不到站牌代碼", result)

    def test_direction_filter_excludes_the_other_direction(self) -> None:
        """台北車站去程/返程各一筆；指定返程時不得混入去程。"""
        result = _run(stop_name="台北車站", direction=1)

        self.assertIn("台北車站", result)
        self.assertIn("S4", result)
        self.assertNotIn("S3", result)

    def test_output_exposes_stop_id_for_reuse(self) -> None:
        result = _run(stop_id="S1")

        self.assertIn("S1", result)


if __name__ == "__main__":
    unittest.main()
