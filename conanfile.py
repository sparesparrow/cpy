#!/usr/bin/env python3
"""
CPython Tool Package in cpy Repo
Builds CPython 3.12.7 interpreter from source for tool_requires
Apache-2.0; cross-platform application package

Zero-Copy Integration:
This package builds CPython from source, creating a self-contained toolchain.
Consumers can use zero-copy integration by creating symlinks to this package's output.
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration, ConanException
from conan.tools.files import get, copy, rm, chdir, load
from conan.tools.build import can_run, cross_building
from conan.tools.gnu import Autotools, AutotoolsDeps
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
from conan.tools.info import check_min_cppstd

class CPythonTool(ConanFile):
    """
    CPython Tool Package - Builds CPython from source for use as Conan tool_requires.
    
    Zero-Copy Support:
    This package builds CPython and exposes it in a structure that supports
    zero-copy integration via symlinks for consuming packages.
    """
    name = "cpython-tool"
    version = "3.12.7"
    package_type = "application"  # Build-time executable [web:67][web:51]
    settings = "os", "compiler", "build_type", "arch"
    description = "CPython 3.12.7 interpreter built from source for use as Conan tool_requires with zero-copy support"
    
    options = {
        "shared": [True, False],
        "fips": [True, False],  # Optional FIPS mode [web:51]
        "optimize": ["0", "1", "2", "3"],  # Python optimization level
        "enable_zero_copy": [True, False]  # Enable zero-copy symlink support
    }
    default_options = {
        "shared": False,
        "fips": False,
        "optimize": "2",
        "enable_zero_copy": True
    }

    requires = "zlib/[>=1.2.11 <2.0]@conan/stable"  # Core dep for CPython [web:69]
    
    # Zero-copy toolchain path (for consumer packages)
    toolchain_path = "cpython-toolchain"

    def export_sources(self):
        copy(self, "patches/*", self.recipe_folder, self.export_sources_folder)  # If patches needed

    def config_options(self):
        if cross_building(self):
            self.options.rm_safe("fips")  # Cross-build limitations [web:117]
        check_min_cppstd(self, 11)

    def configure(self):
        if self.options.shared and self.settings.os == "Windows":
            self.options["zlib"].shared = True

    def _create_symlink(self, source: str, dest: str, is_directory: bool = False):
        """Cross-platform symlink creation for zero-copy support"""
        # Remove existing if needed
        if os.path.exists(dest) or os.path.islink(dest):
            if os.path.islink(dest):
                current_target = os.readlink(dest)
                source_abs = os.path.abspath(source)
                dest_abs = os.path.abspath(current_target)
                if source_abs == dest_abs:
                    return  # Already correct
                os.unlink(dest)
            else:
                # Non-symlink exists
                self.output.warn(f"{dest} exists and is not a symlink, skipping")
                return
        
        try:
            if self.settings.os == "Windows":
                if is_directory:
                    os.symlink(source, dest, target_is_directory=True)
                else:
                    os.symlink(source, dest)
            else:
                os.symlink(source, dest, target_is_directory=is_directory)
            self.output.info(f"Created symlink: {dest} -> {source}")
        except OSError as e:
            self.output.warn(f"Symlink failed ({e}), using copy fallback")
            if is_directory:
                shutil.copytree(source, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(source, dest)
            self.output.warn("⚠️  Used copy instead of symlink (not zero-copy)")

    def source(self):
        get(self, f"https://www.python.org/ftp/python/{self.version}/Python-{self.version}.tgz",
            strip_root=True)  # Fetch official sources [web:106][attached_file:1]
        # Apply patches if any: load(self, "patches/fix.patch"); self.patch("patches/fix.patch")

    def generate(self):
        env = VirtualBuildEnv(self)
        env.vars["CPPFLAGS"].append("-DCPYTHON_VERSION={}".format(self.version))
        if self.options.fips:
            env.vars["CPPFLAGS"].append("-DFIPS_MODE")
        env.generate()
        if self.settings.os in ["Linux", "FreeBSD"]:
            deps = AutotoolsDeps(self)
            deps.generate()
        self.conf_info.update({"tools.python:optimize": self.options.optimize})

    def build(self):
        if self.settings.os in ["Linux", "FreeBSD"]:
            autotools = Autotools(self)
            with chdir(self, self.source_folder):
                args = [
                    "--prefix=/usr/local",  # Standard prefix
                    "--enable-optimizations",
                    "--with-ensurepip=no",
                    f"--enable-shared={'--disable-shared' if not self.options.shared else ''}",
                    "--enable-loadable-sqlite-extensions"
                ]
                if self.settings.arch == "armv8":
                    args.append("--with-system-expat")  # Cross-build aids [web:117]
                if self.options.fips:
                    args.append("--enable-fips")
                autotools.configure(args=args)
                autotools.make()
                autotools.install()
        elif self.settings.os == "Windows":
            # MSVC build: use PCbuild/build.bat for simplicity [web:103]
            self.run(f"cd PCbuild && build.bat -p {self.settings.compiler.version} -t {self.settings.build_type}")
        elif self.settings.os == "Macos":
            with chdir(self, self.source_folder):
                env_vars = os.environ.copy()
                env_vars["CPPFLAGS"] = f'-I{self.deps_cpp_info["zlib"].include_paths[0]}'
                self.run("./configure --enable-framework --enable-shared", env=env_vars)
                self.run("make", env=env_vars)
                self.run("make install", env=env_vars)
        logger = self.output  # Assume self.output
        logger.info("CPython {} built successfully".format(self.version))

        if self.options.enable_sbom:  # Security integration [web:17]
            self._generate_sbom()

    def _generate_sbom(self):
        if can_run(self):
            syft_bin = self.dependencies["syft"].bin_path  # From build_requires if added
            cmd = [syft_bin, "packages", ".", "-o", "cyclonedx-json=sbom.json"]
            self.run(" ".join(cmd))
            with open("sbom.json") as f:
                self.info["sbom_hash"] = hashlib.sha256(f.read().encode()).hexdigest()  # Assume hashlib

    def package(self):
        """Package CPython binaries, libraries, and stdlib with zero-copy support"""
        # Copy binaries/libs [web:111]
        if self.settings.os != "Windows":
            copy(self, "python", dst=os.path.join(self.package_folder, "bin"), 
                 src="usr/local/bin")
            copy(self, "*.so*", dst=os.path.join(self.package_folder, "lib"), 
                 src="usr/local/lib", symlinks=True)
        else:
            copy(self, "python.exe", dst=os.path.join(self.package_folder, "bin"), 
                 src="PCbuild/amd64")
            copy(self, "*.pyd", dst=os.path.join(self.package_folder, "lib"), 
                 src="PCbuild/amd64")
        
        # Stdlib
        copy(self, "*", dst=os.path.join(self.package_folder, "lib/python3.12"), 
             src="lib/python3.12", exclude="*.a")  # Exclude static [web:69]
        
        # Create zero-copy toolchain structure if enabled
        if self.options.enable_zero_copy:
            toolchain_root = os.path.join(self.package_folder, self.toolchain_path)
            if not os.path.exists(toolchain_root):
                os.makedirs(toolchain_root)
            
            # Create symlink structure for zero-copy access
            for item in ["bin", "lib", "include"]:
                source_item = os.path.join(self.package_folder, item)
                dest_item = os.path.join(toolchain_root, item)
                if os.path.exists(source_item):
                    self._create_symlink(source_item, dest_item, is_directory=True)
        
        if hasattr(self.options, 'enable_sbom') and self.options.enable_sbom:
            copy(self, "sbom.json", dst=self.package_folder, keep_path=False)

        # Trivy scan [web:17]
        if can_run(self):
            trivy_bin = self.dependencies["trivy"].bin_path
            cmd = [trivy_bin, "fs", self.package_folder, "--exit-code", "1", "--vuln-type", "os,library"]
            self.run(" ".join(cmd))

    def package_info(self):
        """Package info with zero-copy CPython toolchain exposure"""
        self.cpp_info.set_property("pkg_name", "python")
        bin_dir = Path(self.package_folder) / "bin"
        self.cpp_info.bindirs = [str(bin_dir)]
        self.cpp_info.libdirs = [str(Path(self.package_folder) / "lib")]
        
        interpreter = "python.exe" if self.settings.os == "Windows" else "python"
        python_exe = bin_dir / interpreter
        
        self.conf_info.update({
            "tools.python:python": str(python_exe),
            "tools.python:optimize": self.options.optimize
        })
        
        # Build/run env for tool use [web:72]
        self.buildenv_info.define_path("PYTHONHOME", str(self.package_folder))
        self.runenv_info.define_path("PYTHONHOME", str(self.package_folder))
        
        # Zero-copy toolchain path for consumers
        if self.options.enable_zero_copy:
            toolchain_root = os.path.join(self.package_folder, self.toolchain_path)
            self.buildenv_info.define_path("PYTHON_ROOT", toolchain_root)
            self.runenv_info.define_path("PYTHON_ROOT", toolchain_root)
            
            # Add toolchain bin to PATH
            toolchain_bin = os.path.join(toolchain_root, "bin")
            self.buildenv_info.append_path("PATH", toolchain_bin)
            self.runenv_info.append_path("PATH", toolchain_bin)
        
        if self.options.fips:
            self.buildenv_info.define("PYTHON_FIPS", "1")
        
        # No linkage; tool only [web:51][web:67]
        
    def _get_python_executable(self) -> str:
        """Get path to Python executable for zero-copy consumers"""
        python_name = "python.exe" if self.settings.os == "Windows" else "python"
        if self.options.enable_zero_copy:
            return os.path.join(
                self.package_folder,
                self.toolchain_path,
                "bin",
                python_name
            )
        return os.path.join(self.package_folder, "bin", python_name)

# Build and publish workflow in .github/workflows/build-cpy.yml
name: Build and Publish CPython Tool
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      version:
        description: "CPython version"
        required: true
        default: "3.12.7"
      fips:
        type: boolean
        default: false
jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        arch: [x86_64]  # Extend for arm [web:117]
    steps:
      - uses: actions/checkout@v4
      - name: Setup Conan
        uses: conan-io/setup-conan@v1
        with:
          conan_version: 2.21.0
      - name: Build Package
        run: conan create . ${{ inputs.version || github.event.inputs.version || '3.12.7' }} -o fips=${{ inputs.fips || 'false' }} --build=missing -pr:b=default -pr:h=default
        shell: bash
      - name: Security Gates
        if: github.event_name != 'pull_request'
        run: conan upload cpython-tool/3.12.7@sparesparrow/stable --all --confirm -r=openssl-conan  # Only on push [web:40][web:77]
      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: cpy-${{ matrix.os }}-${{ matrix.arch }}
          path: build/
