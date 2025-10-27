#!/usr/bin/env python3
"""
CPython Tool Package in cpy Repo
Builds CPython 3.12.7 interpreter from source for tool_requires
Apache-2.0; cross-platform application package
"""
import os
from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import get, copy, rm, chdir, load
from conan.tools.build import can_run, cross_building
from conan.tools.gnu import Autotools, AutotoolsDeps
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
from conan.tools.info import check_min_cppstd
from pathlib import Path

class CPythonTool(ConanFile):
    name = "cpython-tool"
    version = "3.12.7"
    package_type = "application"  # Build-time executable [web:67][web:51]
    settings = "os", "compiler", "build_type", "arch"
    options = {
        "shared": [True, False],
        "fips": [True, False],  # Optional FIPS mode [web:51]
        "optimize": ["0", "1", "2", "3"]  # Python optimization level
    }
    default_options = {
        "shared": False,
        "fips": False,
        "optimize": "2"
    }

    requires = "zlib/[>=1.2.11 <2.0]@conan/stable"  # Core dep for CPython [web:69]

    def export_sources(self):
        copy(self, "patches/*", self.recipe_folder, self.export_sources_folder)  # If patches needed

    def config_options(self):
        if cross_building(self):
            self.options.rm_safe("fips")  # Cross-build limitations [web:117]
        check_min_cppstd(self, 11)

    def configure(self):
        if self.options.shared and self.settings.os == "Windows":
            self.options["zlib"].shared = True

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
        # Copy binaries/libs [web:111]
        if self.settings.os != "Windows":
            copy(self, "python", dst=os.path.join(self.package_folder, "bin"), src="usr/local/bin")
            copy(self, "*.so*", dst=os.path.join(self.package_folder, "lib"), src="usr/local/lib", symlinks=True)
        else:
            copy(self, "python.exe", dst=os.path.join(self.package_folder, "bin"), src="PCbuild/amd64")
            copy(self, "*.pyd", dst=os.path.join(self.package_folder, "lib"), src="PCbuild/amd64")
        # Stdlib
        copy(self, "*", dst=os.path.join(self.package_folder, "lib/python3.12"), src="lib/python3.12", exclude="*.a")  # Exclude static [web:69]
        if self.options.enable_sbom:
            copy(self, "sbom.json", dst=self.package_folder, keep_path=False)

        # Trivy scan [web:17]
        if can_run(self):
            trivy_bin = self.dependencies["trivy"].bin_path
            cmd = [trivy_bin, "fs", self.package_folder, "--exit-code", "1", "--vuln-type", "os,library"]
            self.run(" ".join(cmd))

    def package_info(self):
        self.cpp_info.set_property("pkg_name", "python")
        bin_dir = self.package_folder / "bin"
        self.cpp_info.bindirs = [bin_dir]
        self.cpp_info.libdirs = [self.package_folder / "lib"]
        interpreter = "python.exe" if self.settings.os == "Windows" else "python"
        self.conf_info.update({
            "tools.python:python": str(bin_dir / interpreter),
            "tools.python:optimize": self.options.optimize
        })
        # Build/run env for tool use [web:72]
        self.buildenv_info.vars["PYTHONHOME"] = str(self.package_folder)
        if self.options.fips:
            self.buildenv_info.vars["PYTHON_FIPS"] = "1"
        # No linkage; tool only [web:51][web:67]

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
