/* Adapted from: https://m516.github.io/CV-Sandbox/src/05-OpenCV-and-ImGui */
#define GLAD_GL_IMPLEMENTATION
#include "gl.h"
#include <GLFW/glfw3.h>

#include <imgui.h>
#include <imgui_impl_glfw.h>


#include "video_stitcher.hpp"
#include <iostream>
#include <fstream>
#include <thread>
#include <imgui_impl_opengl3.h>

GLFWwindow* window;
int window_width, window_height;
GLuint image_texture;
bool running = true;
cv::Mat pano;
cv::Mat pano_conv;

void setup_stitcher(VideoStitcher *&st, std::vector<std::string> &capture_names) {
    for (;;) {
        try {
            st = new VideoStitcher(capture_names);
            break; // success
        } catch (...) {
            LOGLN("Failed stitcher setup, retrying");
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

static GLuint matUpdateTexture(const GLuint textureID, const cv::Mat& mat, GLenum minFilter, GLenum magFilter, GLenum wrapFilter) {
    // Bind to our texture handle
    glBindTexture(GL_TEXTURE_2D, textureID);

    // Catch silly-mistake texture interpolation method for magnification
    if (magFilter == GL_LINEAR_MIPMAP_LINEAR ||
            magFilter == GL_LINEAR_MIPMAP_NEAREST ||
            magFilter == GL_NEAREST_MIPMAP_LINEAR ||
            magFilter == GL_NEAREST_MIPMAP_NEAREST)
    {
        LOGLN("You can't use MIPMAPs for magnification - setting "
                "filter to GL_LINEAR");
        magFilter = GL_LINEAR;
    }

    // Set texture interpolation methods for minification and magnification
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, minFilter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, magFilter);

    // Set texture clamping method
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrapFilter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrapFilter);

    // Set incoming texture format to:
    // GL_BGR       for CV_CAP_OPENNI_BGR_IMAGE,
    // GL_LUMINANCE for CV_CAP_OPENNI_DISPARITY_MAP,
    // Work out other mappings as required ( there's a list in comments in main() )
    GLenum inputColourFormat = GL_BGR;
    if (mat.channels() == 1)
    {
        inputColourFormat = GL_LUMINANCE;
    }

    // Create the texture
    glTexImage2D(GL_TEXTURE_2D,     // Type of texture
            0,                 // Pyramid level (for mip-mapping) - 0 is the top level
            GL_RGB,            // Internal colour format to convert to
            mat.cols,          // Image width  i.e. 640 for Kinect in standard mode
            mat.rows,          // Image height i.e. 480 for Kinect in standard mode
            0,                 // Border width in pixels (can either be 1 or 0)
            inputColourFormat, // Input image format (i.e. GL_RGB, GL_RGBA, GL_BGR etc.)
            GL_UNSIGNED_BYTE,  // Image data type
            mat.ptr());        // The actual image data itself

    // If we're using mipmaps then generate them. Note: This requires OpenGL 3.0 or higher
    if (minFilter == GL_LINEAR_MIPMAP_LINEAR ||
            minFilter == GL_LINEAR_MIPMAP_NEAREST ||
            minFilter == GL_NEAREST_MIPMAP_LINEAR ||
            minFilter == GL_NEAREST_MIPMAP_NEAREST)
    {
        glGenerateMipmap(GL_TEXTURE_2D);
    }

    return textureID;
}

// Function turn a cv::Mat into a texture, and return the texture ID as a GLuint for use
static GLuint matToTexture(const cv::Mat& mat, GLenum minFilter, GLenum magFilter, GLenum wrapFilter) {
    // Generate a number for our textureID's unique handle
    GLuint textureID;
    glGenTextures(1, &textureID);

    // Bind to our texture handle
    glBindTexture(GL_TEXTURE_2D, textureID);

    // Catch silly-mistake texture interpolation method for magnification
    if (magFilter == GL_LINEAR_MIPMAP_LINEAR ||
            magFilter == GL_LINEAR_MIPMAP_NEAREST ||
            magFilter == GL_NEAREST_MIPMAP_LINEAR ||
            magFilter == GL_NEAREST_MIPMAP_NEAREST)
    {
        LOGLN("You can't use MIPMAPs for magnification - setting "
                "filter to GL_LINEAR");
        magFilter = GL_LINEAR;
    }

    // Set texture interpolation methods for minification and magnification
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, minFilter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, magFilter);

    // Set texture clamping method
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrapFilter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrapFilter);

    // Set incoming texture format to:
    // GL_BGR       for CV_CAP_OPENNI_BGR_IMAGE,
    // GL_LUMINANCE for CV_CAP_OPENNI_DISPARITY_MAP,
    // Work out other mappings as required ( there's a list in comments in main() )
    GLenum inputColourFormat = GL_BGR;
    if (mat.channels() == 1)
    {
        inputColourFormat = GL_LUMINANCE;
    }

    // Create the texture
    glTexImage2D(GL_TEXTURE_2D,     // Type of texture
            0,                 // Pyramid level (for mip-mapping) - 0 is the top level
            GL_RGB,            // Internal colour format to convert to
            mat.cols,          // Image width  i.e. 640 for Kinect in standard mode
            mat.rows,          // Image height i.e. 480 for Kinect in standard mode
            0,                 // Border width in pixels (can either be 1 or 0)
            inputColourFormat, // Input image format (i.e. GL_RGB, GL_RGBA, GL_BGR etc.)
            GL_UNSIGNED_BYTE,  // Image data type
            mat.ptr());        // The actual image data itself

    // If we're using mipmaps then generate them. Note: This requires OpenGL 3.0 or higher
    if (minFilter == GL_LINEAR_MIPMAP_LINEAR ||
            minFilter == GL_LINEAR_MIPMAP_NEAREST ||
            minFilter == GL_NEAREST_MIPMAP_LINEAR ||
            minFilter == GL_NEAREST_MIPMAP_NEAREST)
    {
        glGenerateMipmap(GL_TEXTURE_2D);
    }

    return textureID;
}

void update_texture(VideoStitcher *&st) {
    while (running) {
        if (!st) continue;
        st->getNextFrame(pano);
        pano.convertTo(pano_conv, CV_8U);
        pano = pano_conv;
#ifdef FAKE_SLOW
        struct timespec time = {1, 0};
        nanosleep(&time, NULL);
#endif
    }
}


static void key_callback(GLFWwindow* window, int key, int scancode, int action, int mods) {
    if (key == GLFW_KEY_ESCAPE && action == GLFW_PRESS) {
        glfwSetWindowShouldClose(window, GLFW_TRUE);
    }
}

static void resize_callback(GLFWwindow* window, int new_width, int new_height) {
    glViewport(0, 0, window_width = new_width, window_height = new_height);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(0.0, window_width, window_height, 0.0, 0.0, 100.0);
    glMatrixMode(GL_MODELVIEW);
}

static void init_opengl(int w, int h) {
    glViewport(0, 0, w, h); // use a screen size of WIDTH x HEIGHT

    glMatrixMode(GL_PROJECTION);     // Make a simple 2D projection on the entire window
    glLoadIdentity();
    glOrtho(0.0, w, h, 0.0, 0.0, 100.0);

    glMatrixMode(GL_MODELVIEW);    // Set the matrix mode to object modeling

    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClearDepth(0.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT); // Clear the window
}

/**
 * A helper function for terminating the program
 */
void terminate(int errorCode) {
    LOGLN("Closing application");
    // Close GLFW
    glfwTerminate();
    // Exit
    exit(errorCode);
}


/**
 * A callback function for GLFW to execute when an internal error occurs with the
 * library.
 */
void error_callback(int error, const char* description)
{
    fprintf(stderr, "Error: %s\n", description);
}


void setGuiScale(float guiScale) {
    int fbw, fbh, ww, wh;
    glfwGetFramebufferSize(window, &fbw, &fbh);
    glfwGetWindowSize(window, &ww, &wh);

    float pixelRatio = fbw / (float)ww;

    ImGui::GetIO().FontGlobalScale = guiScale / pixelRatio;
}

#if 1
int main(int argc, char **argv) {
    if (argc < 2) {
        LOGLN("Usage: " << argv[0] << "<at least 2 mjpeg stream urls>");
        return -1;
    }
    std::vector<std::string> args;
    args.reserve(argc - 1);
    for (int i = 1; i < argc; ++i) {
        args.emplace_back(argv[i]);
    }
    std::vector<std::string> capture_names = std::move(args);

    //Attempt to initialize GLFW
    if (!glfwInit())
    {
        //Initialization failed
        std::cerr << "GLFW initialization failed :(";
        //Use the terminate() function to safely close the application
        terminate(1);
    }

    // Decide GL+GLSL versions
#if __APPLE__
    // GL 3.2 + GLSL 150
    const char* glsl_version = "#version 150";
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 2);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);  // 3.2+ only
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);            // Required on Mac
#else
    // GL 3.0 + GLSL 120
    const char* glsl_version = "#version 120";
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);
    //glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);  // 3.2+ only
    //glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);            // 3.0+ only
#endif

    //Set GLFW's error callback function
    glfwSetErrorCallback(error_callback);

    //GLFW creates a window and its OpenGL context with the next function
    window = glfwCreateWindow(640, 480, "OpenCV ImGUI", NULL, NULL);

    //Check for errors (which would happen if creating a window fails
    if (!window)
    {
        // Window or OpenGL context creation failed
        std::cerr << "GLFW failed to create a window and/or OpenGL "
            "context :(";
        //Use the terminate() function to safely close the application
        terminate(1);
    }

    //Window creation was successful. Continue
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1); // Enable vsync

    if (!gladLoadGL((GLADloadfunc)glfwGetProcAddress)) {
        // GLAD failed
        std::cerr << "GLAD failed to initialize :(";
        //Use the terminate() function to safely close the application
        terminate(1);
    }



    // Setup Dear ImGui context
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO(); (void)io;
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    bool show_test_window = true;
    bool show_another_window = false;
    ImVec4 clear_color = ImColor(10, 10, 10);

    //Set scale based on scale of monitor
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float scale = 2.f;
    glfwGetMonitorContentScale(monitor, &scale, nullptr);

    float imageScale = 1.f; //Configurable image scale
    int swapInterval = 1;


    VideoStitcher *st = nullptr;
#if 1
    std::thread setup_thread(setup_stitcher, std::ref(st), std::ref(capture_names));
#else
    for (;;) {
        try {
            st = new VideoStitcher(capture_names);
            break; // success
        } catch (...) {
            LOGLN("Failed stitcher setup, retrying");
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
#endif
    glGenTextures(1, &image_texture);

    // The render loop
    std::thread update_texture_thread(update_texture, std::ref(st));
    while (!glfwWindowShouldClose(window))
    {
        // Render prelude
        {
            glfwPollEvents();
            ImGui_ImplOpenGL3_NewFrame();
            ImGui_ImplGlfw_NewFrame();
            ImGui::NewFrame();

            // ImGui::SetNextWindowSize(ImVec2(320,240));
            ImGui::Begin("Preferences", &show_another_window);
            // Gui rendering size
            if(ImGui::SliderFloat("Display scale", &scale, 1, 3)) setGuiScale(scale);
            // Image rendering size relative to GUI size
            ImGui::SliderFloat("Image scale", &imageScale, 0.1, 4);
            // Framerate division factor
            if (ImGui::SliderInt("Swap interval", &swapInterval, 1, 5)) glfwSwapInterval(swapInterval);
            //Stats
            ImGui::Text("Stats:");
            // Framerate
            ImGui::Text("Application average %.3f ms/frame (%.1f FPS)", 1000.0f / ImGui::GetIO().Framerate, ImGui::GetIO().Framerate);
            ImGui::End();
        }

        // This is not thread safe so call it on each frame rather than every capture
        matUpdateTexture(image_texture, pano, GL_LINEAR_MIPMAP_LINEAR, GL_LINEAR, GL_CLAMP);

        // Render postlude
        {
            // Place the texture in an ImGui image
            ImGui::Begin("Image");
            float ims = scale * imageScale;
            ImVec2 imageSize = ImVec2(ims * pano.size().width, ims * pano.size().height);
            ImGui::Text("texture size = %.0f x %.0f", imageSize.x, imageSize.y);
            ImGui::Text("image size = %d x %d", pano.size().width, pano.size().height);
            ImGui::Image((void*)(intptr_t)image_texture, imageSize);
            ImGui::End();

            // Rendering
            ImGui::Render();
            int display_w, display_h;
            glfwGetFramebufferSize(window, &display_w, &display_h);
            glViewport(0, 0, display_w, display_h);
            glClearColor(clear_color.x, clear_color.y, clear_color.z, clear_color.w);
            glClear(GL_COLOR_BUFFER_BIT);
            ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

            glfwSwapBuffers(window);
            glDeleteTextures(1, &image_texture);
        }
    }
    running = false;
    update_texture_thread.join();
    setup_thread.join();

    // Cleanup
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    glfwDestroyWindow(window);
    glfwTerminate();

    pano.release();
    pano_conv.release();

    return 0;
}
#else
int main(int argc, char** argv) {
    // configure these to match your environment
    std::string file_path = MEDIA_DIRECTORY;
    std::vector<std::string> capture_names {
#if 1
        file_path + "m0.mkv",
        file_path + "m1.mkv",
        file_path + "m2.mkv",
        file_path + "m3.mkv",
        //file_path + "4.mkv",
        //file_path + "5.mkv",
#else
        file_path + "cam0.mp4",
        file_path + "cam1.mp4",
#endif
    };


    VideoStitcher *st;
    try {
        st = new VideoStitcher(capture_names);
    } catch (std::exception e) {
        return -1;
    }

    // Warm-up frames (optional)
    cv::Mat out;
    const int warmup = 5;
    for (int i = 0; i < warmup; ++i) {
        if (st->getNextFrame(out) != 0) { std::cerr << "getNextFrame error during warmup\n"; return 1; }
    }

    // Benchmark parameters
    const double test_seconds = 5.0;
    using clock = std::chrono::high_resolution_clock;
    auto t0 = clock::now();
    auto tend = t0 + std::chrono::duration<double>(test_seconds);

    size_t frames = 0;
    std::chrono::duration<double> total_time{0};

    while (clock::now() < tend) {
        auto s = clock::now();
        int r = st->getNextFrame(out);
        auto e = clock::now();
        if (r != 0) {
            std::cerr << "getNextFrame returned error\n";
            break;
        }
        ++frames;
        total_time += (e - s);
    }

    double avg_frame_ms = (total_time.count() / std::max<size_t>(frames,1)) * 1000.0;
    double fps = frames / total_time.count();

    std::cout << "Benchmark duration (s): " << total_time.count() << "\n";
    std::cout << "Frames processed: " << frames << "\n";
    std::cout << "Average frame time (ms): " << avg_frame_ms << "\n";
    std::cout << "Average FPS: " << fps << "\n";

    return 0;
}
#endif
