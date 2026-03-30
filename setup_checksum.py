"""Build script for the C PaChecksum extension."""

from setuptools import setup, Extension

setup(
    name="pa_checksum",
    ext_modules=[
        Extension(
            "core._pa_checksum",
            sources=["core/_pa_checksum.c"],
        ),
    ],
)
