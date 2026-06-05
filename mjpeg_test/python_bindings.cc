#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <opencv2/opencv.hpp>
#include "video_stitcher.hpp"

namespace py = pybind11;

// Helper: convert cv::Mat -> numpy array (shares memory when possible)
py::array mat_to_nparray(const cv::Mat &mat) {
    std::vector<size_t> shape;
    std::vector<size_t> strides;
    int type = mat.type();
    int channels = mat.channels();

    if (mat.dims != 2) throw std::runtime_error("Only 2D Mats supported");

    shape = { (size_t)mat.rows, (size_t)mat.cols, (size_t)channels };
    strides = {
        (size_t)mat.step[0],
        (size_t)mat.step[1],
        (size_t)(mat.elemSize1())
    };

    // If single-channel, expose shape as (rows, cols)
    if (channels == 1) {
        shape = { (size_t)mat.rows, (size_t)mat.cols };
        strides = { (size_t)mat.step[0], (size_t)mat.step[1] };
    }

    // Map OpenCV depth to format; use dtype auto via buffer protocol
    return py::array(py::buffer_info(
        const_cast<unsigned char*>(mat.data),                 // data pointer
        mat.elemSize1(),                                     // element size
        py::format_descriptor<unsigned char>::format(),      // format (byte-wise)
        shape.size(),                                        // ndim
        shape,                                               // shape
        strides                                              // strides
    ));
}

PYBIND11_MODULE(video_stitcher, m) {
    py::class_<VideoStitcher>(m, "VideoStitcher")
        .def(py::init<const std::vector<std::string>&>(),
             py::arg("file_names"))
        .def("getNextFrame", [](VideoStitcher &self) {
            cv::Mat out;
            // release GIL during heavy C++ work
            py::gil_scoped_release release;
            int rc = self.getNextFrame(out);
            py::gil_scoped_acquire acquire;
            if (rc != 0) throw std::runtime_error("getNextFrame returned error code " + std::to_string(rc));
            return mat_to_nparray(out);
        });

    m.doc() = "Python bindings for VideoStitcher (pybind11)";
}
