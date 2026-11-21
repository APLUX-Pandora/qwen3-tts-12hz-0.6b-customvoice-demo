"""Pandora provider-local Runtime configuration ABI4; native providers own their own opaque handles.

This provider is delivered with Qwen3-TTS. It adds no common inference engine,
process scheduler, or mandatory package named pandora. Bindings pass the native
provider explicitly; a handle is never passed between different SDK libraries.
"""
import ctypes as C
from dataclasses import dataclass
import os

_MODES = {"burst": 0, "sustained_high_performance": 3, "high_performance": 4,
          "balanced": 1, "low_balanced": 5, "high_power_saver": 6,
          "power_saver": 7, "low_power_saver": 8, "extreme_power_saver": 9,
          "system_settings": 2}
_PRIORITIES = {"low": 0, "normal": 100, "normal_high": 150, "high": 200}

@dataclass(frozen=True)
class QnnOptions:
    performance_mode: str = "burst"
    priority: str = "normal"
    device_id: int = 0
    rpc_control_latency_us: int | None = None
    rpc_polling_time_us: int | None = None
    def __post_init__(self):
        if type(self.device_id) is not int:
            raise TypeError("device_id must be a uint32 integer")
        if not 0 <= self.device_id <= 2**32-1:
            raise ValueError("device_id must be in 0..2**32-1")
        for name, choices in (("performance_mode", _MODES), ("priority", _PRIORITIES)):
            value = getattr(self, name)
            if not isinstance(value, str): raise TypeError(name + " must be a string")
            if value not in choices: raise ValueError(name + " must be one of: " + ", ".join(choices))
        for name, limit in (("rpc_control_latency_us", 2**32-1), ("rpc_polling_time_us", 9999)):
            value = getattr(self, name)
            if value is not None:
                if type(value) is not int: raise TypeError(name + " must be an integer or None")
                if not 0 <= value <= limit: raise ValueError(name + " is outside the supported range")
                if self.performance_mode == "system_settings": raise ValueError("system_settings does not accept RPC overrides")

@dataclass(frozen=True)
class CpuOptions:
    affinity: str | tuple[int, ...] = "default"
    def __post_init__(self):
        value = self.affinity
        if isinstance(value, str):
            if value not in ("inherit", "default"):
                raise ValueError("affinity must be inherit, default, or a nonempty CPU collection")
            return
        try:
            values = tuple(value)
        except TypeError as exc:
            raise TypeError("affinity must be a policy string or CPU iterable") from exc
        if not values:
            raise ValueError("CPU collection cannot be empty")
        for cpu in values:
            if type(cpu) is not int:
                raise TypeError("CPU IDs must be integers; bool is not accepted")
            if not 0 <= cpu < 1024:
                raise ValueError("CPU IDs must be in 0..1023 for this provider")
        object.__setattr__(self, "affinity", tuple(sorted(set(values))))

class _Cpu(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32),
                ("policy", C.c_uint32), ("cpu_count", C.c_uint32),
                ("cpu_ids", C.POINTER(C.c_uint32)), ("reserved", C.c_uint32 * 2)]
class _CpuConfig(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32),
                ("linux_soc_id", C.c_uint32), ("present_cpu_count", C.c_uint32),
                ("default_mask", C.c_uint64), ("config_version", C.c_char * 32)]
class _CpuStatus(C.Structure):
    _fields_ = [(k, C.c_uint32) for k in ("struct_size", "abi_version", "policy", "coverage",
                "supported_policies", "backend_override_supported", "active_workers", "observed_threads",
                "verified_threads", "profile_id")] + [("reserved", C.c_uint32 * 2), ("affinity_failures", C.c_uint64)]
class _CpuThread(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32), ("tid", C.c_uint64),
                ("scope", C.c_uint32), ("cpu_count", C.c_uint32), ("verified", C.c_uint32), ("reserved", C.c_uint32)]

class _Qnn(C.Structure):
    _fields_ = [("mode", C.c_uint32), ("priority", C.c_int32), ("device_id", C.c_uint32), ("reserved", C.c_uint32)]
class _Config(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32),
                ("backend", C.c_uint32), ("reserved_protection", C.c_uint32), ("qnn", _Qnn), ("override_flags", C.c_uint32),
                ("rpc_control_latency_us", C.c_uint32), ("rpc_polling_time_us", C.c_uint32), ("reserved", C.c_uint32), ("cpu", _Cpu)]
class _Status(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("abi_version", C.c_uint32),
                ("performance_mode", C.c_uint32), ("priority", C.c_int32),
                ("reserved_protection", C.c_uint32), ("active_contexts", C.c_uint32),
                ("power_client_created", C.c_uint32), ("active_executions", C.c_uint32),
                ("accepted_active_votes", C.c_uint64), ("accepted_release_votes", C.c_uint64),
                ("rpc_control_latency_us", C.c_uint32), ("rpc_polling_time_us", C.c_uint32),
                ("process_rpc_polling_time_us", C.c_uint32), ("deferred_vote_failures", C.c_uint32),
                ("device_id", C.c_uint32), ("execution_device_id", C.c_uint32),
                ("power_device_id", C.c_uint32), ("core_id", C.c_uint32), ("device_verified", C.c_uint32)]

class RuntimeNativeError(RuntimeError):
    """Native provider failure with a machine-readable SDK error code."""
    def __init__(self, code, message):
        super().__init__(message + " (code " + str(code) + ")")
        self.code = self.native_code = code

class _Protection(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("attached_models", C.c_uint32),
                ("mapped_bytes", C.c_uint64), ("locked_bytes", C.c_uint64), ("lock_failures", C.c_uint64),
                ("authorization_checks", C.c_uint64), ("key_provider_calls", C.c_uint64),
                ("decrypt_calls", C.c_uint64), ("backend_initialization_attempts", C.c_uint64),
                ("quarantined_backend_failures", C.c_uint64)]

class Runtime:
    """Immutable configuration and a process-local, provider-bound native runtime.

    Defaults: CPU default, backend='qnn', burst, normal priority, device 0. Native
    creation is deferred until a model binds this runtime. Use one application
    thread to load/close; model execution may overlap under its API contract.
    """
    def __init__(self, *, cpu=None, qnn=None, backend="qnn"):
        if backend != "qnn": raise ValueError("Only the qnn backend is supported")
        if cpu is None: cpu = CpuOptions()
        if qnn is None: qnn = QnnOptions()
        if not isinstance(cpu, CpuOptions): raise TypeError("cpu must be CpuOptions")
        if not isinstance(qnn, QnnOptions): raise TypeError("qnn must be QnnOptions")
        self._cpu, self._qnn = cpu, qnn
        self._close_error = None
        self._pid = os.getpid()
        self._slot, self._lib, self._closed = C.c_void_p(), None, False
    @property
    def cpu(self): return self._cpu
    @property
    def qnn(self): return self._qnn
    def _check(self):
        if os.getpid() != self._pid:
            raise RuntimeError("Runtime inherited through fork; create a new runtime and model after spawn/exec")
        if self._closed: raise RuntimeError("Runtime is closed")
    def _error(self, rc):
        if rc < 0:
            raise RuntimeNativeError(rc, self._lib.pandora_runtime_last_error().decode(errors="replace"))
    def _bind(self, lib):
        self._check()
        if self._lib is not None and self._lib._handle != lib._handle:
            raise RuntimeError("A native Runtime cannot be shared across different SDK providers")
        if not self._slot.value:
            self._lib = lib
            lib.pandora_runtime_last_error.restype = C.c_char_p
            lib.pandora_runtime_create.argtypes = [C.POINTER(_Config), C.POINTER(C.c_void_p)]
            lib.pandora_runtime_create.restype = C.c_int
            lib.pandora_runtime_get_status.argtypes = [C.c_void_p, C.POINTER(_Status)]
            lib.pandora_runtime_get_status.restype = C.c_int
            lib.pandora_runtime_destroy.argtypes = [C.POINTER(C.c_void_p)]
            lib.pandora_runtime_destroy.restype = C.c_int
            c = _Config(C.sizeof(_Config), 4, 1, 0,
                        _Qnn(_MODES[self.qnn.performance_mode], _PRIORITIES[self.qnn.priority], self.qnn.device_id, 0))
            for name, flag in (("rpc_control_latency_us", 1), ("rpc_polling_time_us", 2)):
                value = getattr(self.qnn, name)
                if value is not None:
                    c.override_flags |= flag; setattr(c, name, value)
            affinity = self.cpu.affinity
            ids = None if isinstance(affinity, str) else (C.c_uint32 * len(affinity))(*affinity)
            policy = {"inherit": 0, "default": 1}[affinity] if isinstance(affinity, str) else 2
            c.cpu = _Cpu(C.sizeof(_Cpu), 1, policy, len(ids) if ids is not None else 0, ids)
            try: self._error(lib.pandora_runtime_create(C.byref(c), C.byref(self._slot)))
            except BaseException:
                if self._slot.value: lib.pandora_runtime_destroy(C.byref(self._slot))
                raise
        return self._slot.value
    def status(self):
        self._check()
        result = {"device_id": self.qnn.device_id, "execution_device_id": None,
                  "power_device_id": None, "core_id": None, "device_verified": False, "backend": "qnn", "performance_mode": self.qnn.performance_mode,
                  "priority": self.qnn.priority,
                  "active_contexts": 0, "power_client_created": False, "active_executions": 0,
                  "accepted_active_votes": 0, "accepted_release_votes": 0, "deferred_vote_failures": 0,
                  "rpc_control_latency_us": (self.qnn.rpc_control_latency_us if self.qnn.rpc_control_latency_us is not None else (0 if self.qnn.performance_mode == "system_settings" else 100)),
                  "rpc_polling_time_us": None,
                  "process_rpc_polling_time_us": None}
        if self._slot.value:
            s = _Status(); s.struct_size, s.abi_version = C.sizeof(s), 4
            self._error(self._lib.pandora_runtime_get_status(self._slot, C.byref(s)))
            for k in ("active_contexts", "active_executions", "accepted_active_votes", "accepted_release_votes", "rpc_control_latency_us", "rpc_polling_time_us", "deferred_vote_failures"):
                result[k] = getattr(s, k)
            for name in ("device_id", "execution_device_id", "power_device_id", "core_id"):
                value = getattr(s, name)
                result[name] = None if name != "device_id" and value == 2**32-1 else value
            result["device_verified"] = bool(s.device_verified)
            result["performance_mode"] = next(name for name, value in _MODES.items() if value == s.performance_mode)
            result["priority"] = next(name for name, value in _PRIORITIES.items() if value == s.priority)
            result["rpc_polling_time_us"] = None if s.rpc_polling_time_us == 2**32-1 else s.rpc_polling_time_us
            result["power_client_created"] = bool(s.power_client_created)
            result["process_rpc_polling_time_us"] = None if s.process_rpc_polling_time_us == 2**32-1 else s.process_rpc_polling_time_us
        result["configuration_submitted"] = bool(result["active_contexts"])
        result["performance_scope"] = "direct QNN Talker, Code Predictor and Codec"
        result["priority_scope"] = "normal only; other priorities are not implemented"
        result["vendor_power_management"] = False
        result["vendor_power_scope"] = "none; AIDEM/LMS supplies protected model loading"
        result["attached_models"] = 0
        for name in ("authorization_checks","key_provider_calls","decrypt_calls",
                     "backend_initialization_attempts","quarantined_backend_failures"):
            result[name] = 0
        result["mapped_bytes"] = result["locked_bytes"] = result["lock_failures"] = 0
        if self._slot.value:
            self._lib.q3t_get_protection_status.argtypes = [C.c_void_p, C.POINTER(_Protection)]
            self._lib.q3t_get_protection_status.restype = C.c_int
            protection = _Protection(); protection.struct_size = C.sizeof(protection)
            self._error(self._lib.q3t_get_protection_status(self._slot, C.byref(protection)))
            for name, _ in _Protection._fields_[1:]:
                result[name] = getattr(protection, name)
        if result["locked_bytes"] == 2**64-1: result["locked_bytes"] = None
        result["protection_counters_scope"] = "mapped/lock counters: SDK-wide; attempts/quarantine: per Runtime cumulative; not a per-model release assertion"
        result["cpu"] = self.cpu_status()
        return result
    def cpu_status(self):
        """Read native configuration and live owner TID masks; synchronize with close."""
        self._check()
        result = {"affinity": self.cpu.affinity, "bound": bool(self._slot.value),
                  "resolved": None, "allowed": None, "defaults": None, "threads": []}
        if not self._slot.value:
            return result
        lib = self._lib
        P = C.c_void_p
        for name, args in (
            ("pandora_runtime_get_cpu_config", [P, C.POINTER(_CpuConfig)]),
            ("pandora_runtime_get_cpu_status", [P, C.POINTER(_CpuStatus)]),
            ("pandora_runtime_get_cpu_ids", [P, C.c_uint32, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]),
            ("pandora_runtime_get_cpu_thread", [P, C.c_uint32, C.POINTER(_CpuThread), C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)])):
            fn = getattr(lib, name); fn.argtypes = args; fn.restype = C.c_int
        config = _CpuConfig(); config.struct_size, config.abi_version = C.sizeof(config), 1
        self._error(lib.pandora_runtime_get_cpu_config(self._slot, C.byref(config)))
        status = _CpuStatus(); status.struct_size, status.abi_version = C.sizeof(status), 1
        self._error(lib.pandora_runtime_get_cpu_status(self._slot, C.byref(status)))
        result.update(linux_soc_id=config.linux_soc_id, present_cpu_count=config.present_cpu_count,
                      default_mask=config.default_mask, config_version=config.config_version.decode(),
                      active_workers=status.active_workers, observed_threads=status.observed_threads,
                      verified_threads=status.verified_threads, profile_id=status.profile_id,
                      affinity_failures=status.affinity_failures,
                      observation_scope="SDK-owned model/control workers; backend descendants need separate validation")
        for kind, name in enumerate(("allowed", "resolved", "defaults")):
            ids = (C.c_uint32 * 1024)(); count = C.c_uint32(1024)
            self._error(lib.pandora_runtime_get_cpu_ids(self._slot, kind, ids, C.byref(count)))
            result[name] = list(ids[:count.value])
        for index in range(status.observed_threads):
            thread = _CpuThread(); thread.struct_size, thread.abi_version = C.sizeof(thread), 1
            ids = (C.c_uint32 * 1024)(); count = C.c_uint32(1024)
            self._error(lib.pandora_runtime_get_cpu_thread(self._slot, index, C.byref(thread), ids, C.byref(count)))
            result["threads"].append({"tid": thread.tid, "scope": thread.scope,
                                      "cpus": list(ids[:count.value]), "verified": bool(thread.verified)})
        return result
    def close(self):
        if os.getpid() != self._pid: raise RuntimeError("Cannot close a Runtime inherited through fork")
        if self._closed:
            if self._close_error is not None: raise self._close_error
            return
        if self._slot.value:
            if self.status()["attached_models"]:
                raise RuntimeError("Close attached models before closing the Runtime")
            rc = self._lib.pandora_runtime_destroy(C.byref(self._slot))
            if rc < 0:
                failure = RuntimeNativeError(rc, self._lib.pandora_runtime_last_error().decode(errors="replace"))
                if not self._slot.value: self._closed, self._close_error = True, failure
                raise failure
        self._closed = True
    def __enter__(self): self._check(); return self
    def __exit__(self, *_): self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
