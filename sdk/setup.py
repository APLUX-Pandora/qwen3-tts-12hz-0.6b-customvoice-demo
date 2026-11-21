"""Install the matching prebuilt model library without compiling it."""
import platform
import runpy
from pathlib import Path
import shutil
from setuptools import setup, Distribution
from setuptools.command.build_py import build_py
ROOT=Path(__file__).resolve().parent
PACKAGE="pandora_qwen3_tts_12hz_0_6b_customvoice"
class NativeDistribution(Distribution):
    def has_ext_modules(self): return True
class BuildSDK(build_py):
    def run(self):
        library=ROOT/"lib/libqwen3_tts.so"
        if not library.is_file(): raise RuntimeError("Stage the matching prebuilt SDK library before installation")
        if platform.system()!="Linux" or platform.machine().lower() not in ("aarch64","arm64"):
            raise RuntimeError("The native SDK requires Linux AArch64 with LMS and compatible BSP/FastRPC")
        runpy.run_path(str(ROOT/"verify_native.py"))["verify"](ROOT)
        super().run()
        target=Path(self.build_lib)/PACKAGE/"lib"
        target.mkdir(parents=True,exist_ok=True)
        shutil.copy2(library,target/library.name)
        runtime=ROOT/"lib/qnn248"
        if not runtime.is_dir(): raise RuntimeError("Matching embedded QNN runtime is missing")
        shutil.copytree(runtime,target/"qnn248",dirs_exist_ok=True)
        for name in ("LICENSE","LICENSE.zh-CN.txt","THIRD_PARTY_NOTICES.txt","LICENSES"):
            source=ROOT/"lib"/name
            if not source.exists(): raise RuntimeError("Missing SDK legal material: "+name)
            if source.is_dir(): shutil.copytree(source,target/name,dirs_exist_ok=True)
            else: shutil.copy2(source,target/name)
setup(package_dir={"":"python"},packages=[PACKAGE],cmdclass={"build_py":BuildSDK},distclass=NativeDistribution)
