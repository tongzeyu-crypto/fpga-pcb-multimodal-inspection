"""Regression for the Windows reader/atomic-rename collision found in packaging."""
from pathlib import Path
import ctypes, os, tempfile, threading, time, unittest
from runtime.demo_integration import atomic_snapshot


@unittest.skipUnless(os.name=='nt','Windows file sharing semantics')
class SnapshotChecks(unittest.TestCase):
    def test_active_reader_releases_before_atomic_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'demo-view.txt';path.write_text('previous complete snapshot')
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
            api.CreateFileW.restype=ctypes.c_void_p
            api.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=api.CreateFileW(str(path),0x80000000,1,None,3,0,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            def release():
                time.sleep(.04);api.CloseHandle(handle)
            reader=threading.Thread(target=release);reader.start()
            try:retries=atomic_snapshot(path,'new complete snapshot')
            finally:reader.join()
            self.assertGreater(retries,0)
            self.assertEqual(path.read_text(),'new complete snapshot')
            self.assertFalse(path.with_suffix('.tmp').exists())


if __name__=='__main__':unittest.main()
