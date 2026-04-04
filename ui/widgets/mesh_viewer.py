"""3D mesh preview widget with a fast OpenGL path and optimized fallback.

The viewer prefers a hardware-accelerated ``QOpenGLWidget`` when the runtime
has ``PyOpenGL`` available. If that stack is missing or fails, it falls back to
an optimized software renderer that projects vertices once per frame and uses a
lighter interactive mode while dragging.
"""

from __future__ import annotations

import ctypes
import math
from array import array
from dataclasses import dataclass
import numpy as np

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QBrush, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

try:
    from OpenGL.GL import (
        GL_ARRAY_BUFFER,
        GL_COLOR_BUFFER_BIT,
        GL_COMPILE_STATUS,
        GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST,
        GL_ELEMENT_ARRAY_BUFFER,
        GL_FALSE,
        GL_FLOAT,
        GL_FRAGMENT_SHADER,
        GL_LINK_STATUS,
        GL_MULTISAMPLE,
        GL_STATIC_DRAW,
        GL_TRUE,
        GL_TRIANGLES,
        GL_UNSIGNED_INT,
        GL_VERTEX_SHADER,
        glAttachShader,
        glBindBuffer,
        glBindVertexArray,
        glBufferData,
        glClear,
        glClearColor,
        glCompileShader,
        glCreateProgram,
        glCreateShader,
        glDeleteShader,
        glDrawElements,
        glEnable,
        glEnableVertexAttribArray,
        glGenBuffers,
        glGenVertexArrays,
        glGetProgramInfoLog,
        glGetProgramiv,
        glGetShaderInfoLog,
        glGetShaderiv,
        glGetUniformLocation,
        glLinkProgram,
        glShaderSource,
        glUniform3f,
        glUniform3fv,
        glUniformMatrix4fv,
        glUseProgram,
        glVertexAttribPointer,
        glViewport,
    )
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtOpenGLWidgets import QOpenGLWidget

    _GL_RUNTIME_AVAILABLE = True
except Exception:
    QSurfaceFormat = None
    QOpenGLWidget = None
    _GL_RUNTIME_AVAILABLE = False


_VIEWER_HELP_TEXT = "Drag to rotate | Middle drag to pan | Scroll to zoom"


def _vec_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_length(v):
    return math.sqrt(_vec_dot(v, v))


def _vec_normalize(v):
    length = _vec_length(v)
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    inv = 1.0 / length
    return (v[0] * inv, v[1] * inv, v[2] * inv)


def _face_normal(v0, v1, v2):
    return _vec_normalize(_vec_cross(_vec_sub(v1, v0), _vec_sub(v2, v0)))


def _as_gl_float_buffer(values):
    """Return a ctypes float buffer compatible with PyOpenGL uniform uploads."""
    return (ctypes.c_float * len(values))(*[float(v) for v in values])


class _SoftwareMeshViewer(QWidget):
    """CPU fallback mesh viewer with a cheaper interactive rendering path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vertices = []
        self._normals = []
        self._faces = []
        self._face_normals = []
        self._rot_x = -25.0
        self._rot_y = 35.0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._last_mouse = None
        self._center = (0.0, 0.0, 0.0)
        self._scale = 1.0
        self._info_text = ""
        self._interactive = False
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_mesh(self, vertices, faces, normals=None, info_text=""):
        self._vertices = list(vertices)
        if normals and len(normals) == len(self._vertices):
            self._normals = [tuple(n) for n in normals]
        else:
            self._normals = []
        self._faces = list(faces)
        self._info_text = info_text
        self._pan = QPointF(0.0, 0.0)
        self._zoom = 1.0
        self._interactive = False

        if not self._vertices:
            self._face_normals = []
            self.update()
            return

        xs = [v[0] for v in self._vertices]
        ys = [v[1] for v in self._vertices]
        zs = [v[2] for v in self._vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        self._center = (
            (min_x + max_x) / 2.0,
            (min_y + max_y) / 2.0,
            (min_z + max_z) / 2.0,
        )

        extent = max(max_x - min_x, max_y - min_y, max_z - min_z, 0.001)
        self._scale = 1.0 / extent

        self._face_normals = []
        for a, b, c in self._faces:
            if a < len(self._vertices) and b < len(self._vertices) and c < len(self._vertices):
                if self._normals:
                    avg = _vec_add(
                        _vec_add(self._normals[a], self._normals[b]),
                        self._normals[c],
                    )
                    self._face_normals.append(_vec_normalize(avg))
                else:
                    self._face_normals.append(_face_normal(
                        self._vertices[a], self._vertices[b], self._vertices[c]
                    ))
            else:
                self._face_normals.append((0.0, 1.0, 0.0))

        self.update()

    def clear(self):
        self._vertices = []
        self._normals = []
        self._faces = []
        self._face_normals = []
        self._info_text = ""
        self._interactive = False
        self.update()

    def _project_vertices(self):
        if not self._vertices:
            return []

        scale = self._scale * self._zoom * min(self.width(), self.height()) * 0.35
        ry = math.radians(self._rot_y)
        rx = math.radians(self._rot_x)
        cos_y = math.cos(ry)
        sin_y = math.sin(ry)
        cos_x = math.cos(rx)
        sin_x = math.sin(rx)
        cx = self.width() * 0.5 + self._pan.x()
        cy = self.height() * 0.5 + self._pan.y()

        out = []
        for vx, vy, vz in self._vertices:
            x = (vx - self._center[0]) * scale
            y = (vy - self._center[1]) * scale
            z = (vz - self._center[2]) * scale

            x2 = x * cos_y + z * sin_y
            z2 = -x * sin_y + z * cos_y
            y2 = y * cos_x - z2 * sin_x
            z3 = y * sin_x + z2 * cos_x

            out.append((cx + x2, cy - y2, z3))
        return out

    def paintEvent(self, event):
        painter = QPainter(self)
        interactive_fast = self._interactive and len(self._faces) > 4000
        painter.setRenderHint(QPainter.Antialiasing, not interactive_fast and len(self._faces) < 15000)
        painter.fillRect(self.rect(), QColor(24, 24, 37))

        if not self._vertices or not self._faces:
            painter.setPen(QColor(108, 112, 134))
            painter.drawText(self.rect(), Qt.AlignCenter, self._info_text or "No mesh loaded")
            painter.end()
            return

        projected = self._project_vertices()
        if not projected:
            painter.end()
            return

        light = _vec_normalize((0.3, 0.7, 0.5))

        if interactive_fast:
            step = max(1, len(self._faces) // 3500)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(120, 160, 220, 180), 0.6))
            for face_idx in range(0, len(self._faces), step):
                a, b, c = self._faces[face_idx]
                if a >= len(projected) or b >= len(projected) or c >= len(projected):
                    continue
                p0 = projected[a]
                p1 = projected[b]
                p2 = projected[c]
                area = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
                if area < 0.02:
                    continue
                painter.drawPolygon(QPolygonF([
                    QPointF(p0[0], p0[1]),
                    QPointF(p1[0], p1[1]),
                    QPointF(p2[0], p2[1]),
                ]))
        else:
            face_draws = []
            for face_idx, (a, b, c) in enumerate(self._faces):
                if a >= len(projected) or b >= len(projected) or c >= len(projected):
                    continue
                p0 = projected[a]
                p1 = projected[b]
                p2 = projected[c]
                area = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
                if area < 0.02:
                    continue

                normal = self._face_normals[face_idx] if face_idx < len(self._face_normals) else (0.0, 1.0, 0.0)
                dot = max(0.15, _vec_dot(normal, light))
                face_draws.append(((p0[2] + p1[2] + p2[2]) / 3.0, p0, p1, p2, dot))

            face_draws.sort(key=lambda item: item[0])
            for _, p0, p1, p2, dot in face_draws:
                r = int(min(255, 80 + 100 * dot))
                g = int(min(255, 120 + 80 * dot))
                b = int(min(255, 180 + 60 * dot))
                painter.setBrush(QBrush(QColor(r, g, b, 220)))
                painter.setPen(QPen(QColor(40, 42, 54), 0.5))
                painter.drawPolygon(QPolygonF([
                    QPointF(p0[0], p0[1]),
                    QPointF(p1[0], p1[1]),
                    QPointF(p2[0], p2[1]),
                ]))

        painter.setPen(QColor(166, 173, 200))
        if self._info_text:
            painter.drawText(8, 16, self._info_text)
        painter.setPen(QColor(108, 112, 134))
        painter.drawText(8, self.height() - 8, _VIEWER_HELP_TEXT)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        self._last_mouse = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._last_mouse is None:
            return

        dx = event.position().x() - self._last_mouse.x()
        dy = event.position().y() - self._last_mouse.y()
        self._last_mouse = event.position()

        if event.buttons() & Qt.LeftButton:
            self._interactive = True
            self._rot_y += dx * 0.5
            self._rot_x += dy * 0.5
            self._rot_x = max(-90.0, min(90.0, self._rot_x))
            self.update()
        elif event.buttons() & Qt.MiddleButton:
            self._interactive = True
            self._pan = QPointF(self._pan.x() + dx, self._pan.y() + dy)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._last_mouse = None
        if self._interactive:
            self._interactive = False
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom *= 1.15
        else:
            self._zoom /= 1.15
        self._zoom = max(0.1, min(20.0, self._zoom))
        self.update()


if _GL_RUNTIME_AVAILABLE:
    @dataclass
    class _GpuMesh:
        positions: np.ndarray
        normals: np.ndarray
        indices: np.ndarray
        center: tuple[float, float, float]
        radius: float


    class _OrbitCamera:
        def __init__(self):
            self.yaw = 0.0
            self.pitch = 0.3
            self.radius = 2.0
            self.target = np.zeros(3, dtype=np.float32)
            self.fov_y = 45.0
            self._last_x = 0.0
            self._last_y = 0.0

        def fit_to_sphere(self, center, radius):
            self.target = np.array(center, dtype=np.float32)
            half_fov = math.radians(self.fov_y * 0.5)
            self.radius = max(radius / max(math.sin(half_fov), 1e-6) * 1.3, 0.01)
            self.yaw = math.pi
            self.pitch = 0.3

        def eye_position(self):
            cp, sp = math.cos(self.pitch), math.sin(self.pitch)
            cy, sy = math.cos(self.yaw), math.sin(self.yaw)
            return self.target + self.radius * np.array([cp * sy, sp, cp * cy], dtype=np.float32)

        def view_matrix(self):
            eye = self.eye_position()
            forward = self.target - eye
            forward_len = float(np.linalg.norm(forward))
            if forward_len < 1e-8:
                return np.eye(4, dtype=np.float32)
            forward /= forward_len
            world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            right = np.cross(forward, world_up)
            right_len = float(np.linalg.norm(right))
            if right_len < 1e-8:
                right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            else:
                right /= right_len
            up = np.cross(right, forward)

            m = np.eye(4, dtype=np.float32)
            m[0, :3] = right
            m[1, :3] = up
            m[2, :3] = -forward
            m[0, 3] = -float(np.dot(right, eye))
            m[1, 3] = -float(np.dot(up, eye))
            m[2, 3] = float(np.dot(forward, eye))
            return m

        def proj_matrix(self, aspect):
            near = max(self.radius * 0.001, 0.001)
            far = self.radius * 100.0
            f = 1.0 / math.tan(math.radians(self.fov_y) * 0.5)
            m = np.zeros((4, 4), dtype=np.float32)
            m[0, 0] = f / max(aspect, 1e-6)
            m[1, 1] = f
            m[2, 2] = (far + near) / (near - far)
            m[2, 3] = (2.0 * far * near) / (near - far)
            m[3, 2] = -1.0
            return m

        def handle_press(self, x, y):
            self._last_x = x
            self._last_y = y

        def handle_move(self, buttons, x, y):
            dx = x - self._last_x
            dy = y - self._last_y
            self._last_x = x
            self._last_y = y

            if buttons & Qt.LeftButton:
                self.yaw -= dx * 0.005
                self.pitch += dy * 0.005
                self.pitch = max(-1.5, min(1.5, self.pitch))
            elif buttons & Qt.MiddleButton:
                cp = math.cos(self.pitch)
                sp = math.sin(self.pitch)
                cy = math.cos(self.yaw)
                sy = math.sin(self.yaw)
                right = (cy, 0.0, -sy)
                up = (-sp * sy, cp, -sp * cy)
                scale = self.radius * 0.002
                self.target = _vec_add(self.target, _vec_add(
                    _vec_scale(right, -dx * scale),
                    _vec_scale(up, dy * scale),
                ))

        def handle_scroll(self, delta):
            self.radius *= 0.9 ** (delta / 120.0)
            self.radius = max(0.01, self.radius)


    _VERT_SHADER = """#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
uniform mat4 uMVP;
out vec3 vNormal;
void main() {
    vNormal = aNormal;
    gl_Position = uMVP * vec4(aPos, 1.0);
}
"""

    _FRAG_SHADER = """#version 330 core
in vec3 vNormal;
out vec4 FragColor;
uniform vec3 uLightDir;
uniform vec3 uColor;
void main() {
    vec3 N = normalize(vNormal);
    vec3 L = normalize(uLightDir);
    float diff = max(abs(dot(N, L)), 0.0);
    vec3 ambient = 0.18 * uColor;
    vec3 diffuse = 0.82 * diff * uColor;
    FragColor = vec4(ambient + diffuse, 1.0);
}
"""


    class _OpenGLMeshViewer(QOpenGLWidget):
        """Hardware accelerated mesh viewer."""

        def __init__(self, parent=None):
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            fmt.setSamples(4)
            fmt.setDepthBufferSize(24)
            super().__init__(parent)
            self.setFormat(fmt)
            self._vertices = []
            self._normals = []
            self._faces = []
            self._info_text = ""
            self._camera = _OrbitCamera()
            self._program = 0
            self._vao = 0
            self._vbo_pos = 0
            self._vbo_nor = 0
            self._ebo = 0
            self._index_count = 0
            self._has_mesh = False
            self._gl_ready = False
            self._gl_error = ""
            self._pending_mesh = None
            self.setMinimumSize(200, 200)
            self.setMouseTracking(True)
            self.setFocusPolicy(Qt.StrongFocus)

        def set_mesh(self, vertices, faces, normals=None, info_text=""):
            self._vertices = list(vertices)
            if normals and len(normals) == len(self._vertices):
                self._normals = [tuple(n) for n in normals]
            else:
                self._normals = []
            self._faces = list(faces)
            self._info_text = info_text

            if not self._vertices or not self._faces:
                self.clear()
                return

            self._pending_mesh = self._build_gpu_mesh(self._vertices, self._faces, self._normals)
            if self._gl_ready and self.context():
                self._upload_mesh(self._pending_mesh)
            self.update()

        def clear(self):
            self._has_mesh = False
            self._pending_mesh = None
            self._vertices = []
            self._normals = []
            self._faces = []
            self.update()

        def initializeGL(self):
            try:
                glEnable(GL_DEPTH_TEST)
                glEnable(GL_MULTISAMPLE)
                glClearColor(0.10, 0.10, 0.18, 1.0)
                self._compile_shaders()
                self._setup_buffers()
                self._gl_ready = True
                if self._pending_mesh is not None:
                    self._upload_mesh(self._pending_mesh)
            except Exception as exc:
                self._gl_error = str(exc)
                self._gl_ready = False
                self._has_mesh = False

        def resizeGL(self, width, height):
            glViewport(0, 0, width, height)

        def paintGL(self):
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            if not (self._gl_ready and self._has_mesh):
                return
            try:
                aspect = self.width() / max(self.height(), 1)
                mvp = self._camera.proj_matrix(aspect) @ self._camera.view_matrix()
                glUseProgram(self._program)
                glUniformMatrix4fv(
                    glGetUniformLocation(self._program, "uMVP"),
                    1,
                    GL_TRUE,
                    mvp.astype(np.float32),
                )
                light = np.array([0.6, 0.8, 0.5], dtype=np.float32)
                light /= np.linalg.norm(light)
                glUniform3fv(
                    glGetUniformLocation(self._program, "uLightDir"),
                    1,
                    light,
                )
                glUniform3f(glGetUniformLocation(self._program, "uColor"), 0.72, 0.72, 0.76)
                glBindVertexArray(self._vao)
                glDrawElements(GL_TRIANGLES, self._index_count, GL_UNSIGNED_INT, None)
                glBindVertexArray(0)
            except Exception as exc:
                self._gl_error = str(exc)
                self._gl_ready = False

        def mousePressEvent(self, event: QMouseEvent):
            self._camera.handle_press(event.position().x(), event.position().y())

        def mouseMoveEvent(self, event: QMouseEvent):
            self._camera.handle_move(event.buttons(), event.position().x(), event.position().y())
            self.update()

        def wheelEvent(self, event: QWheelEvent):
            self._camera.handle_scroll(event.angleDelta().y())
            self.update()

        def _build_gpu_mesh(self, vertices, faces, normals=None) -> _GpuMesh:
            if normals and len(normals) == len(vertices):
                vertex_normals = [list(_vec_normalize(tuple(n))) for n in normals]
            else:
                vertex_normals = [[0.0, 0.0, 0.0] for _ in vertices]
                for a, b, c in faces:
                    if a >= len(vertices) or b >= len(vertices) or c >= len(vertices):
                        continue
                    normal = _face_normal(vertices[a], vertices[b], vertices[c])
                    for idx in (a, b, c):
                        vertex_normals[idx][0] += normal[0]
                        vertex_normals[idx][1] += normal[1]
                        vertex_normals[idx][2] += normal[2]

            positions = []
            packed_normals = []
            for idx, vertex in enumerate(vertices):
                positions.append([float(vertex[0]), float(vertex[1]), float(vertex[2])])
                normal = _vec_normalize(tuple(vertex_normals[idx]))
                packed_normals.append([float(normal[0]), float(normal[1]), float(normal[2])])

            indices = []
            for a, b, c in faces:
                if a < len(vertices) and b < len(vertices) and c < len(vertices):
                    indices.extend((a, b, c))

            if vertices:
                min_x = min(v[0] for v in vertices)
                max_x = max(v[0] for v in vertices)
                min_y = min(v[1] for v in vertices)
                max_y = max(v[1] for v in vertices)
                min_z = min(v[2] for v in vertices)
                max_z = max(v[2] for v in vertices)
                # Match CDMB's viewer fit so near/far clipping behaves the same on skewed meshes.
                center = (
                    (min_x + max_x) * 0.5,
                    (min_y + max_y) * 0.5,
                    (min_z + max_z) * 0.5,
                )
                radius = max((_vec_length(_vec_sub(v, center)) for v in vertices), default=0.01)
            else:
                center = (0.0, 0.0, 0.0)
                radius = 0.01

            return _GpuMesh(
                positions=np.array(positions, dtype=np.float32),
                normals=np.array(packed_normals, dtype=np.float32),
                indices=np.array(indices, dtype=np.uint32),
                center=center,
                radius=max(radius, 0.01),
            )

        def _upload_mesh(self, mesh: _GpuMesh):
            if not self._gl_ready or mesh is None:
                return

            self.makeCurrent()
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo_pos)
            glBufferData(GL_ARRAY_BUFFER, mesh.positions.nbytes, mesh.positions.tobytes(), GL_STATIC_DRAW)
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo_nor)
            glBufferData(GL_ARRAY_BUFFER, mesh.normals.nbytes, mesh.normals.tobytes(), GL_STATIC_DRAW)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, mesh.indices.nbytes, mesh.indices.tobytes(), GL_STATIC_DRAW)
            self._index_count = len(mesh.indices)
            self._has_mesh = True
            self._camera.fit_to_sphere(mesh.center, mesh.radius)
            self.doneCurrent()

        def _compile_shaders(self):
            vertex_shader = glCreateShader(GL_VERTEX_SHADER)
            glShaderSource(vertex_shader, _VERT_SHADER)
            glCompileShader(vertex_shader)
            if not glGetShaderiv(vertex_shader, GL_COMPILE_STATUS):
                raise RuntimeError(glGetShaderInfoLog(vertex_shader).decode(errors="replace"))

            fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
            glShaderSource(fragment_shader, _FRAG_SHADER)
            glCompileShader(fragment_shader)
            if not glGetShaderiv(fragment_shader, GL_COMPILE_STATUS):
                raise RuntimeError(glGetShaderInfoLog(fragment_shader).decode(errors="replace"))

            self._program = glCreateProgram()
            glAttachShader(self._program, vertex_shader)
            glAttachShader(self._program, fragment_shader)
            glLinkProgram(self._program)
            if not glGetProgramiv(self._program, GL_LINK_STATUS):
                raise RuntimeError(glGetProgramInfoLog(self._program).decode(errors="replace"))

            glDeleteShader(vertex_shader)
            glDeleteShader(fragment_shader)

        def _setup_buffers(self):
            self._vao = glGenVertexArrays(1)
            self._vbo_pos, self._vbo_nor = glGenBuffers(2)
            self._ebo = glGenBuffers(1)

            glBindVertexArray(self._vao)

            glBindBuffer(GL_ARRAY_BUFFER, self._vbo_pos)
            glBufferData(GL_ARRAY_BUFFER, 0, None, GL_STATIC_DRAW)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 12, None)
            glEnableVertexAttribArray(0)

            glBindBuffer(GL_ARRAY_BUFFER, self._vbo_nor)
            glBufferData(GL_ARRAY_BUFFER, 0, None, GL_STATIC_DRAW)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 12, None)
            glEnableVertexAttribArray(1)

            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, 0, None, GL_STATIC_DRAW)
            glBindVertexArray(0)


    MeshViewer = _OpenGLMeshViewer
else:
    MeshViewer = _SoftwareMeshViewer
