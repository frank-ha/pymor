# This file is part of the pyMOR project (http://www.pymor.org).
# Copyright Holders: Rene Milk, Stephan Rave, Felix Schindler
# License: BSD 2-Clause License (http://opensource.org/licenses/BSD-2-Clause)

""" This module provides a widget for displaying patch plots of
scalar data assigned to a 2D-Grid using OpenGL. This widget is not
intended to be used directly. Instead, use
:meth:`~pymor.gui.qt.visualize_patch` or
:class:`~pymor.gui.qt.PatchVisualizer`.
"""

from __future__ import absolute_import, division, print_function

import math as m

import numpy as np

try:
    from PySide.QtOpenGL import QGLWidget
    from PySide.QtGui import QSizePolicy, QPainter, QFontMetrics
    HAVE_PYSIDE = True
except ImportError:
    HAVE_PYSIDE = False

try:
    import OpenGL.GL as gl
    HAVE_GL = True
except ImportError:
    HAVE_GL = False

HAVE_ALL = HAVE_PYSIDE and HAVE_GL


if HAVE_ALL:
    from ctypes import c_void_p

    from pymor.grids.constructions import flatten_grid
    from pymor.grids.referenceelements import triangle, square

    def compile_shader(source, vertex=True):
        """Compile a vertex shader from source."""
        shader_type = gl.GL_VERTEX_SHADER if vertex else gl.GL_FRAGMENT_SHADER
        shader = gl.glCreateShader(shader_type)
        gl.glShaderSource(shader, source)
        gl.glCompileShader(shader)
        # check compilation error
        result = gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS)
        if not result:
            raise RuntimeError(gl.glGetShaderInfoLog(shader))
        return shader

    def link_shader_program(shaders):
        """Create a shader program with from compiled shaders."""
        program = gl.glCreateProgram()
        for shader in shaders:
            gl.glAttachShader(program, shader)
        gl.glLinkProgram(program)
        # check linking error
        result = gl.glGetProgramiv(program, gl.GL_LINK_STATUS)
        if not result:
            raise RuntimeError(gl.glGetProgramInfoLog(program))
        return program

    VS = """
    #version 120
    // Attribute variable that contains coordinates of the vertices.
    attribute vec3 position;
    varying float value;

    void main()
    {
        gl_Position.xy = position.xy;
        gl_Position.z = 0.;
        gl_Position.w = 1.;
        value = position.z;
    }
    """

    FS = """
    #version 120

    uniform sampler1D colormap;

    varying float value;

    void main()
    {
        gl_FragColor = texture1D(colormap, value);
    }
    """

    def colormap_texture(name='YlGnBu_r'):
        resolution = min(gl.GL_MAX_TEXTURE_SIZE, 1024)
        colormap_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_1D, colormap_id)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_1D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        colormap = np.empty((resolution, 4), dtype='f4')
        import matplotlib.cm
        colormap[:] = getattr(matplotlib.cm, name)(np.linspace(0., 1., resolution))
        gl.glTexImage1D(gl.GL_TEXTURE_1D, 0, gl.GL_RGBA, resolution, 0, gl.GL_RGBA, gl.GL_FLOAT, colormap)
        gl.glBindTexture(gl.GL_TEXTURE_1D, 0)
        return colormap_id

    class GLPatchWidget(QGLWidget):

        def __init__(self, parent, grid, vmin=None, vmax=None, bounding_box=([0, 0], [1, 1]), codim=2):
            assert grid.reference_element in (triangle, square)
            assert grid.dim == 2
            assert codim in (0, 2)
            super(GLPatchWidget, self).__init__(parent)
            self.setMinimumSize(300, 300)
            self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))

            subentities, coordinates, entity_map = flatten_grid(grid)

            self.subentities = subentities
            self.entity_map = entity_map
            self.reference_element = grid.reference_element
            self.vmin = vmin
            self.vmax = vmax
            self.bounding_box = bounding_box
            self.codim = codim
            self.update_vbo = False
            bb = self.bounding_box
            self.size = np.array([bb[1][0] - bb[0][0], bb[1][1] - bb[0][1]])
            self.scale = 2 / self.size
            self.shift = - np.array(bb[0]) - self.size / 2

            # setup buffers
            if self.reference_element == triangle:
                if codim == 2:
                    self.vertex_data = np.empty(len(coordinates),
                                                dtype=[('position', 'f4', 2), ('color', 'f4', 1)])
                    self.indices = subentities
                else:
                    self.vertex_data = np.empty(len(subentities) * 3,
                                                dtype=[('position', 'f4', 2), ('color', 'f4', 1)])
                    self.indices = np.arange(len(subentities) * 3, dtype=np.uint32)
            else:
                if codim == 2:
                    self.vertex_data = np.empty(len(coordinates),
                                                dtype=[('position', 'f4', 2), ('color', 'f4', 1)])
                    self.indices = np.vstack((subentities[:, 0:3], subentities[:, [0, 2, 3]]))
                else:
                    self.vertex_data = np.empty(len(subentities) * 6,
                                                dtype=[('position', 'f4', 2), ('color', 'f4', 1)])
                    self.indices = np.arange(len(subentities) * 6, dtype=np.uint32)

            self.vertex_data['color'] = 1


            self.set_coordinates(coordinates)
            self.set(np.zeros(grid.size(codim)))

        def resizeGL(self, w, h):
            gl.glViewport(0, 0, w, h)
            gl.glLoadIdentity()
            self.update()

        def initializeGL(self):
            gl.glClearColor(1.0, 1.0, 1.0, 1.0)

            self.shaders_program = link_shader_program([compile_shader(VS, vertex=True),
                                                        compile_shader(FS, vertex=False)])
            gl.glUseProgram(self.shaders_program)

            self.vertices_id = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vertices_id)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, self.vertex_data, gl.GL_DYNAMIC_DRAW)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

            self.indices_id = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.indices_id)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, self.indices, gl.GL_STATIC_DRAW)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)

            self.colormap_id = colormap_texture()
            self.colormap_location = gl.glGetUniformLocation(self.shaders_program, 'colormap')

        def paintGL(self):
            if self.update_vbo:
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vertices_id)
                gl.glBufferData(gl.GL_ARRAY_BUFFER, self.vertex_data, gl.GL_DYNAMIC_DRAW)
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
                self.update_vbo = False

            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

            gl.glUniform1i(self.colormap_location, 0)
            gl.glActiveTexture(gl.GL_TEXTURE0 + 0)
            gl.glBindTexture(gl.GL_TEXTURE_1D, self.colormap_id)

            gl.glPushClientAttrib(gl.GL_CLIENT_VERTEX_ARRAY_BIT)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vertices_id)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.indices_id)

            gl.glVertexPointer(3, gl.GL_FLOAT, 0, c_void_p(None))
            gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
            gl.glDrawElements(gl.GL_TRIANGLES, self.indices.size, gl.GL_UNSIGNED_INT, None)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            gl.glPopClientAttrib()

        def set_coordinates(self, coordinates):
            if self.codim == 2:
                self.vertex_data['position'][:, 0:2] = coordinates
                self.vertex_data['position'][:, 0:2] += self.shift
                self.vertex_data['position'][:, 0:2] *= self.scale
            elif self.reference_element == triangle:
                VERTEX_POS = coordinates[self.subentities]
                VERTEX_POS += self.shift
                VERTEX_POS *= self.scale
                self.vertex_data['position'][:, 0:2] = VERTEX_POS.reshape((-1, 2))
            else:
                num_entities = len(self.subentities)
                VERTEX_POS = coordinates[self.subentities]
                VERTEX_POS += self.shift
                VERTEX_POS *= self.scale
                self.vertex_data['position'][0:num_entities * 3, 0:2] = VERTEX_POS[:, 0:3, :].reshape((-1, 2))
                self.vertex_data['position'][num_entities * 3:, 0:2] = VERTEX_POS[:, [0, 2, 3], :].reshape((-1, 2))
            self.update_vbo = True
            self.update()

        def set(self, U):
            U_buffer = self.vertex_data['color']
            if self.codim == 2:
                U_buffer[:] = U[self.entity_map]
            elif self.reference_element == triangle:
                U_buffer[:] = np.repeat(U, 3)
            else:
                U_buffer[:] = np.tile(np.repeat(U, 3), 2)

            # normalize
            vmin = np.min(U) if self.vmin is None else self.vmin
            vmax = np.max(U) if self.vmax is None else self.vmax
            U_buffer -= vmin
            if (vmax - vmin) > 0:
                U_buffer /= float(vmax - vmin)

            self.update_vbo = True
            self.update()

    class ColorBarWidget(QGLWidget):

        def __init__(self, parent, U=None, vmin=None, vmax=None):
            super(ColorBarWidget, self).__init__(parent)
            self.setSizePolicy(QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding))
            self.setAutoFillBackground(False)
            self.set(U, vmin, vmax)

        def resizeGL(self, w, h):
            gl.glViewport(0, 0, w, h)
            gl.glLoadIdentity()
            self.update()

        def initializeGL(self):
            gl.glClearColor(1.0, 1.0, 1.0, 1.0)
            self.shaders_program = link_shader_program([compile_shader(VS, vertex=True),
                                                        compile_shader(FS, vertex=False)])
            gl.glUseProgram(self.shaders_program)

            self.colormap_id = colormap_texture()
            self.colormap_location = gl.glGetUniformLocation(self.shaders_program, 'colormap')

        def set(self, U=None, vmin=None, vmax=None):
            # normalize U
            fm = QFontMetrics(self.font())
            self.vmin = vmin if vmin is not None else (np.min(U) if U is not None else 0.)
            self.vmax = vmax if vmax is not None else (np.max(U) if U is not None else 1.)
            precision = m.log(max(abs(self.vmin), abs(self.vmax) / abs(self.vmin - self.vmax)), 10) + 1
            precision = int(min(max(precision, 3), 8))
            self.vmin_str = format(('{:.' + str(precision) + '}').format(self.vmin))
            self.vmax_str = format(('{:.' + str(precision) + '}').format(self.vmax))
            self.vmin_width = fm.width(self.vmin_str)
            self.vmax_width = fm.width(self.vmax_str)
            self.text_height = fm.height() * 1.5
            self.text_ascent = fm.ascent() * 1.5
            self.text_descent = fm.descent() * 1.5
            self.setMinimumSize(max(self.vmin_width, self.vmax_width) + 20, 300)
            self.update()

        def paintGL(self):
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            gl.glUseProgram(self.shaders_program)

            gl.glUniform1i(self.colormap_location, 0)
            gl.glActiveTexture(gl.GL_TEXTURE0 + 0)
            gl.glBindTexture(gl.GL_TEXTURE_1D, self.colormap_id)

            gl.glBegin(gl.GL_QUAD_STRIP)
            bar_start = -1 + self.text_height / self.height() * 2
            bar_height = (1 - 2 * self.text_height / self.height()) * 2
            steps = 40
            for i in xrange(steps + 1):
                y = i * (1 / steps)
                # gl.glColor(y, 0, 0)
                gl.glVertex(-0.5, (bar_height*y + bar_start), y)
                gl.glVertex(0.5, (bar_height*y + bar_start), y)
            gl.glEnd()
            p = QPainter(self)
            p.drawText((self.width() - self.vmax_width)/2, self.text_ascent, self.vmax_str)
            p.drawText((self.width() - self.vmin_width)/2, self.height() - self.text_height + self.text_ascent,
                       self.vmin_str)
            p.end()

else:

    class GLPatchWidget(object):
        pass

    class ColorBarWidget(object):
        pass
