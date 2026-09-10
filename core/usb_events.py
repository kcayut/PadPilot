"""Native IOKit notifications; callbacks only wake the existing reconciliation loop."""
import ctypes as C
import threading

from core.logger import get_logger

logger = get_logger('USBEvents')


class USBEventMonitor:
    def __init__(self, wake):
        self.wake = wake
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.error = ''

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.ready.clear()
        self.error = ''
        self.thread = threading.Thread(target=self._run, name='PadPilot-USB', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        port = source = loop = None
        iterators = []
        try:
            io = C.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
            cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            callback_type = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32)
            signatures = [
                (io, 'IONotificationPortCreate', C.c_void_p, [C.c_uint32]),
                (io, 'IONotificationPortGetRunLoopSource', C.c_void_p, [C.c_void_p]),
                (io, 'IONotificationPortDestroy', None, [C.c_void_p]),
                (io, 'IOServiceMatching', C.c_void_p, [C.c_char_p]),
                (io, 'IOServiceAddMatchingNotification', C.c_int, [C.c_void_p, C.c_char_p,
                    C.c_void_p, callback_type, C.c_void_p, C.POINTER(C.c_uint32)]),
                (io, 'IOIteratorNext', C.c_uint32, [C.c_uint32]),
                (io, 'IOObjectRelease', C.c_int, [C.c_uint32]),
                (cf, 'CFRunLoopGetCurrent', C.c_void_p, []),
                (cf, 'CFRunLoopAddSource', None, [C.c_void_p, C.c_void_p, C.c_void_p]),
                (cf, 'CFRunLoopRemoveSource', None, [C.c_void_p, C.c_void_p, C.c_void_p]),
                (cf, 'CFRunLoopRunInMode', C.c_int, [C.c_void_p, C.c_double, C.c_bool]),
            ]
            for lib, name, result, args in signatures:
                function = getattr(lib, name)
                function.restype, function.argtypes = result, args
            mode = C.c_void_p.in_dll(cf, 'kCFRunLoopDefaultMode')
            port = io.IONotificationPortCreate(0)
            if not port:
                raise RuntimeError('IONotificationPortCreate failed')
            source = io.IONotificationPortGetRunLoopSource(port)
            if not source:
                raise RuntimeError('IONotificationPortGetRunLoopSource failed')
            loop = cf.CFRunLoopGetCurrent()
            cf.CFRunLoopAddSource(loop, source, mode)

            def drain(iterator):
                changed = False
                while True:
                    device = io.IOIteratorNext(iterator)
                    if not device:
                        return changed
                    io.IOObjectRelease(device)
                    changed = True

            @callback_type
            def callback(_context, iterator):
                if drain(iterator) and not self.stopped.is_set():
                    self.wake()

            for notification in (b'IOServiceFirstMatch', b'IOServiceTerminate'):
                matching = io.IOServiceMatching(b'IOUSBHostDevice')
                if not matching:
                    raise RuntimeError('IOServiceMatching failed')
                iterator = C.c_uint32()
                result = io.IOServiceAddMatchingNotification(
                    port, notification, matching, callback, None, C.byref(iterator))
                if iterator.value:
                    iterators.append(iterator.value)
                if result:
                    raise RuntimeError(f'IOServiceAddMatchingNotification failed: {result}')
                drain(iterator.value)  # Initial enumeration arms notifications, not a hotplug.
            logger.info('Native USB notifications active')
            self.ready.set()
            while not self.stopped.is_set():
                # The timeout only bounds shutdown; USB callbacks arrive immediately.
                cf.CFRunLoopRunInMode(mode, 0.5, True)
        except Exception as exc:
            self.error = f'USB 事件監聽失敗，改用 Watchdog：{exc}'
            logger.warning(self.error)
            self.wake()
        finally:
            if loop and source:
                cf.CFRunLoopRemoveSource(loop, source, mode)
            for iterator in iterators:
                io.IOObjectRelease(iterator)
            if port:
                io.IONotificationPortDestroy(port)
            self.ready.set()
