import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from coordinates import to_wgs84, validate
from iphone_control import ControlError, PhoneController


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
        self.control.location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock(),
                                                service=SimpleNamespace(invoke=AsyncMock()))
        self.control.device_info = SimpleNamespace(mach_kernel_name=AsyncMock())
        sleeper = patch('iphone_control.asyncio.sleep', new_callable=AsyncMock)
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

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

    async def test_restore_reply_keeps_record_until_phone_verified(self):
        self.control._mark_pending(31, 121)
        result = await self.control.restore()
        self.control.location.clear.assert_not_awaited()
        self.control.location.service.invoke.assert_awaited_once_with(
            'stopLocationSimulation', expects_reply=True)
        self.assertEqual(result['status'], 'awaiting_verification')
        self.assertFalse(result['verified'])
        pending = PhoneController(state_path=self.path).pending
        self.assertEqual(pending['status'], 'awaiting_verification')
        self.assertEqual((pending['latitude'], pending['longitude']), (31, 121))
        self.sleep.assert_awaited_once_with(1)
        await self.control.confirm_restored()
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.control.pending)

    async def test_timeout_reconnects_and_retries_once(self):
        self.control._mark_pending(31, 121)
        self.control.location.service.invoke.side_effect = [TimeoutError(), None]
        await self.control.restore()
        self.assertEqual(self.control._connect_location.await_count, 2)
        self.assertEqual(self.control._disconnect.await_count, 2)
        self.assertEqual(self.control.pending['status'], 'awaiting_verification')

    async def test_persistent_timeout_never_claims_acknowledgement(self):
        self.control._mark_pending(31, 121)
        self.control.location.service.invoke.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.control.restore()
        self.assertEqual(self.control.location.service.invoke.await_count, 2)
        self.assertEqual(self.control.pending['status'], 'restore_requested')
        self.assertTrue(self.path.exists())

    async def test_standalone_clear_failure_still_records_recovery(self):
        self.control._connect_location.side_effect = ConnectionError()
        with self.assertRaises(ConnectionError):
            await self.control.restore()
        self.assertEqual(PhoneController(state_path=self.path).pending['udid'], 'test-device')
        self.assertEqual(self.control.pending['status'], 'restore_requested')

    async def test_confirmation_requires_acknowledged_stop(self):
        with self.assertRaises(ControlError):
            await self.control.confirm_restored()
        self.control._mark_pending(31, 121)
        with self.assertRaises(ControlError):
            await self.control.confirm_restored()
        self.assertTrue(self.path.exists())

    async def test_new_simulation_invalidates_previous_verification(self):
        self.control._mark_pending(31, 121)
        await self.control.restore()
        await self.control.set_location(32, 122)
        self.assertEqual(self.control.pending['status'], 'simulating')
        with self.assertRaises(ControlError):
            await self.control.confirm_restored()

    async def test_shutdown_keeps_unverified_restore_without_repeating(self):
        self.control._mark_pending(31, 121)
        await self.control.restore()
        await self.control.shutdown()
        self.control.location.service.invoke.assert_awaited_once()
        self.assertTrue(self.path.exists())

    async def test_diagnostic_reboot_record_accepts_user_verification(self):
        self.control._save_pending({'udid': 'test-device', 'status': 'restart_requested'})
        await self.control.confirm_restored()
        self.assertIsNone(self.control.pending)
        self.assertFalse(self.path.exists())
        self.control.prepare.assert_not_awaited()

    async def test_shutdown_after_diagnostic_reboot_does_not_reopen_services(self):
        self.control._save_pending({'udid': 'test-device', 'status': 'restart_requested'})
        await self.control.shutdown()
        self.control.prepare.assert_not_awaited()
        self.control.location.service.invoke.assert_not_awaited()
        self.assertTrue(self.path.exists())

    async def test_shutdown_restores_active_simulation(self):
        self.control._mark_pending(31, 121)
        await self.control.shutdown()
        self.control.location.service.invoke.assert_awaited_once()
        self.assertEqual(self.control.pending['status'], 'awaiting_verification')

    async def test_restore_cancellation_preserves_record_and_disconnects(self):
        import asyncio
        self.control._mark_pending(31, 121)
        self.control.location.service.invoke.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.control.restore()
        self.assertEqual(self.control.pending['status'], 'restore_requested')
        self.control._disconnect.assert_awaited_once()

    async def test_legacy_record_can_be_restored(self):
        self.path.write_text('{"udid": "test-device", "latitude": 31, "longitude": 121}')
        self.control.pending = self.control._load_pending()
        await self.control.restore()
        self.assertEqual(self.control.pending['status'], 'awaiting_verification')

    async def test_invalid_input_never_connects(self):
        with self.assertRaises(ValueError):
            await self.control.set_location('nan', 121)
        self.control.prepare.assert_not_awaited()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
