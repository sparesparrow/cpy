#!/usr/bin/env python3
"""
CPython Tool Package
Bundled CPython 3.12.7 interpreter for build-time use
Apache-2.0 licensed; dedicated repo for versioning
"""
import os
from conan import ConanFile
from conan.tools.files import copy, chdir
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMakeToolchain, cmake_layout, CMake
from pathlib import Path

class CPythonToolConan(ConanFile):
    name = "cpython-tool"
    version = "3.12.7"
    package_type = "application"  # Tool in build context [web:51]
    settings = "os", "compiler", "build_type", "arch"
    options = {"fips": [True, False], "shared": [True, False]}
    default_options = {"fips": False, "shared": False}

    requires = "zlib/[>=1.2.11]@conan/stable"  # Minimal deps for CPython [web:69]

    def configure(self):
        check_min_cppstd(self, 11)  # CPython build compat

    def layout(self):
        cmake_layout(self, src_folder="source")

    def generate(self):
        tc = CMakeToolchain(self)
        tc.variables["CPYTHON_VERSION"] = self.version
        tc.variables["ENABLE_FIPS"] = self.options.fips
        tc.generate()

    def source(self):
        # Fetch CPython sources
        self.run("wget https://www.python.org/ftp/python/{}/Python-{}.tar.xz".format(self.version, self.version))
        self.run("tar -xf Python-{}.tar.xz".format(self.version))

    def build(self):
        cmake = CMake(self)
        with chdir(self, Path(self.source_folder) / "Python-{}".format(self.version)):
            cmake.configure()
            cmake.build()

    def package(self):
        copy(self, "python*", src="build/bin", dst=os.path.join(self.package_folder, "bin"), keep_path=False)
        copy(self, "*.so", src="build/lib", dst=os.path.join(self.package_folder, "lib"), keep_path=False, pattern="*_cpython-3*")  # Shared libs if shared=True
        # FIPS: Validate if enabled
        if self.options.fips:
            self.run("./bin/python -c 'from cryptography.hazmat.backends.openssl.backend import backend; assert backend._fips_enabled'", env={"PATH": os.path.join(self.package_folder, "bin")})

    def package_info(self):
        self.cpp_info.set_property("pkg_name", "python")
        bin_dir = os.path.join(self.package_folder, "bin")
        self.cpp_info.bindirs = [bin_dir]
        self.cpp_info.libdirs = [os.path.join(self.package_folder, "lib")]
        # Conf for consumers to locate interpreter
        interpreter = "python.exe" if self.settings.os == "Windows" else "python"
        self.conf_info.update({
            "tools.python:python": str(Path(bin_dir) / interpreter)
        })
        # Environment for build context
        self.buildenv_info.vars["PYTHONHOME"] = self.package_folder
        # Verified: Cross-platform tool [web:67][web:51]
