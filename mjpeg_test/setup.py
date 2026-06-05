from setuptools import setup, Extension

setup(
    name="video_stitcher",
    version="0.0.1",
    ext_modules=[
        Extension("video_stitcher", ["video_stitcher_python_wrapper.cc"])
    ]
)
