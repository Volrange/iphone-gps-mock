import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace

from coordinates import to_wgs84, validate
from iphone_control import PhoneController


class CoordinateTests(unittest.TestCase):
    def test_invalid_values(self):
        for lat, lon in [(float('nan'), 0), (0, float('inf')), (91, 0), (0, -181)]:
            with self.assertRaises(ValueError):
                validate(lat, lon)

    def test_reference_and_outside_china(self):
        lat, lon = to_wgs84(39.910226, 116.403714, 'GCJ-02')
        self.assertAlmostEqual(lat, 39.908823, places=5)
        self.assertAlmostEqual(lon, 116.397470, places=5)
        self.assertEqual(to_wgs84(51.5, -0.12, 'GCJ-02'), (51.5, -0.12))


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'pending.json'
        self.control = PhoneController(state_path=self.path)
        self.control.udid = 'test-device'
        self.control.prepare = AsyncMock()
        self.control._connect_location = AsyncMock()
        self.control._disconnect = AsyncMock()
        self.control.location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        self.control.device_info = SimpleNamespace(mach_kernel_name=AsyncMock())

    async def test_set_failure_preserves_recovery_across_restart(self):
        self.control.location.set.side_effect = ConnectionError('disconnected')
        with self.assertRaises(ConnectionError):
            await self.control.set_location(31, 121)
        self.assertEqual(PhoneController(state_path=self.path).pending['udid'], 'test-device')
        self.control._disconnect.assert_awaited_once()

    async def test_restore_failure_preserves_record(self):
        self.control._mark_pending(31, 121)
        self.control.device_info.mach_kernel_name.side_effect = ConnectionError('disconnected')
        with self.assertRaises(ConnectionError):
            await self.control.restore()
        self.assertTrue(self.path.exists())
        self.assertIsNotNone(self.control.pending)

    async def test_restore_success_removes_record(self):
        self.control._mark_pending(31, 121)
        await self.control.restore()
        self.control.location.clear.assert_awaited_once()
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.control.pending)

    async def test_invalid_input_never_connects(self):
        with self.assertRaises(ValueError):
            await self.control.set_location('nan', 121)
        self.control.prepare.assert_not_awaited()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
