# -*- coding: utf-8 -*-
#
# This file is part of NINJA-IDE (http://ninja-ide.org).
#
# NINJA-IDE is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# any later version.
#
# NINJA-IDE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with NINJA-IDE; If not, see <http://www.gnu.org/licenses/>.


import re
import sre_constants

from collections import OrderedDict

from typing import Tuple
from PyQt5.QtWidgets import (
    QPlainTextEdit,
    QAbstractSlider,
    QTextEdit
)
from PyQt5.QtGui import (
    QKeyEvent,
    QTextCursor,
    QTextBlock,
    QTextDocument,
    QKeySequence,
    QColor,
    QTextBlockUserData,

    QFontMetrics,
    QTextOption,
    QTextCharFormat,
    QPaintEvent
)
from PyQt5.QtCore import (
    pyqtSignal,
    QTimer,
    pyqtSlot,
    QPoint,
    Qt
)
from ninja_ide.gui.ide import IDE
from ninja_ide.gui.editor import (
    highlighter,
    scrollbar
)

from ninja_ide.gui.editor.side_area import (
    manager,
    line_number_widget,
    text_change_widget,
    marker_widget,
    code_folding
    # lint_area
)
from ninja_ide.gui.editor import extra_selection
from ninja_ide import resources
from ninja_ide.core import settings
from ninja_ide.gui.editor.extensions import (
    line_highlighter,
    symbol_highlighter,
    margin_line,
    indentation_guides,
    braces,
    quotes
)
from ninja_ide.gui.editor import indenter
from ninja_ide.tools.logger import NinjaLogger
logger = NinjaLogger(__name__)

# FIXME: cursor width and blinking
# FIXME: clone editor for spliting


class NEditor(QPlainTextEdit):
    """Ninja-IDE Editor"""

    # Editor signals
    fontChanged = pyqtSignal('QString')
    zoomChanged = pyqtSignal(int)
    editorFocusObtained = pyqtSignal()
    cursor_position_changed = pyqtSignal(int, int)
    keyPressed = pyqtSignal(QKeyEvent)
    postKeyPressed = pyqtSignal(QKeyEvent)
    painted = pyqtSignal(QPaintEvent)
    current_line_changed = pyqtSignal(int)
    # FIXME: cambiar esto
    highlight_checker_updated = pyqtSignal('PyQt_PyObject')
    addBackItemNavigation = pyqtSignal()

    @property
    def nfile(self):
        return self._neditable.nfile

    @property
    def neditable(self):
        return self._neditable

    @property
    def file_path(self):
        return self._neditable.file_path

    @property
    def is_modified(self) -> bool:
        return self.document().isModified()

    @property
    def visible_blocks(self) -> Tuple[int, int, QTextBlock]:
        return self.__visible_blocks

    @property
    def default_font(self):
        return self.document().defaultFont()

    @default_font.setter
    def default_font(self, font):
        QPlainTextEdit.setFont(self, font)
        self._update_tab_stop_width()

    @property
    def encoding(self):
        if self.__encoding is not None:
            return self.__encoding
        return 'utf-8'

    @encoding.setter
    def encoding(self, encoding):
        self.__encoding = encoding

    @property
    def cursor_position(self) -> Tuple[int, int]:
        """Get or set the current cursor position.

        :param position: The position to set.
        :type position: tuple(line, column).
        :return: Current cursor position in document.
        :rtype: tuple(line, colum)."""

        cursor = self.textCursor()
        return (cursor.blockNumber(), cursor.columnNumber())

    @cursor_position.setter
    def cursor_position(self, position):
        line, column = position
        line = min(line, self.line_count() - 1)
        column = min(column, len(self.line_text(line)))
        cursor = QTextCursor(self.document().findBlockByNumber(line))
        cursor.setPosition(cursor.block().position() + column,
                           QTextCursor.MoveAnchor)
        self.setTextCursor(cursor)

    @property
    def background_color(self) -> QColor:
        """Get or set the background color.

        :param color: Color to set (name or hexa).
        :type color: QColor or str.
        :return: Background color.
        :rtype: QColor."""

        return self._background_color

    @background_color.setter
    def background_color(self, color):
        if isinstance(color, str):
            color = QColor(color)
        self._background_color = color
        # Refresh stylesheet
        self.__apply_style()

    @property
    def foreground_color(self):
        """Get or set the foreground color.
        :param color: Color to set (name or hexa).
        :type color: QColor or str.
        :return: Foreground color.
        :rtype: QColor"""

        return self._foreground_color

    @foreground_color.setter
    def foreground_color(self, color):
        if isinstance(color, str):
            color = QColor(color)
        self._foreground_color = color
        self.__apply_style()

    @property
    def show_whitespaces(self):
        return self.__show_whitespaces

    @show_whitespaces.setter
    def show_whitespaces(self, show):
        if self.__show_whitespaces != show:
            self.__show_whitespaces = show
            self.__set_whitespaces_flags(show)

    @property
    def margins(self):
        return self.__margins

    @property
    def brace_matching(self):
        return self._brace_matching.actived

    @brace_matching.setter
    def brace_matching(self, value):
        self._brace_matching.actived = value

    @property
    def highlight_current_line(self):
        return self._line_highlighter.actived

    @highlight_current_line.setter
    def highlight_current_line(self, value):
        self._line_highlighter.actived = value

    @property
    def current_line_mode(self):
        return self._line_highlighter.mode

    @current_line_mode.setter
    def current_line_mode(self, mode):
        self._line_highlighter.mode = mode

    @property
    def margin_line(self):
        return self._margin_line.actived

    @margin_line.setter
    def margin_line(self, value):
        self._margin_line.actived = value

    @property
    def margin_line_position(self):
        return self._margin_line.position

    @margin_line_position.setter
    def margin_line_position(self, position):
        self._margin_line.position = position

    @property
    def margin_line_background(self):
        return self._margin_line.background

    @margin_line_background.setter
    def margin_line_background(self, value):
        self._margin_line.background = value

    def __init__(self, neditable):
        QPlainTextEdit.__init__(self)
        self.setFrameStyle(0)  # Remove border
        self._neditable = neditable
        self.setMouseTracking(True)
        # Style
        self.__init_style()
        self.__apply_style()

        self.setCursorWidth(2)  # FIXME: from setting
        self.__visible_blocks = []
        self._last_line_position = 0
        self.__encoding = None
        self.__show_whitespaces = settings.SHOW_TABS_AND_SPACES
        # Extra Selections
        self._extra_selections = OrderedDict()
        self.__occurrences = []
        # Load indenter based on language
        # self._highlighter = None
        self._indenter = indenter.load_indenter(self, neditable.language())
        # Set editor font before build lexer
        self.set_font(settings.FONT)
        # self.register_syntax_for(neditable.language())
        # Register extensions
        self.__extensions = {}
        # Brace matching
        self._brace_matching = self.register_extension(
            symbol_highlighter.SymbolHighlighter)
        self.brace_matching = settings.BRACE_MATCHING
        # Current line highlighter
        self._line_highlighter = self.register_extension(
            line_highlighter.CurrentLineHighlighter)
        self.highlight_current_line = settings.HIGHLIGHT_CURRENT_LINE
        # Right margin line
        self._margin_line = self.register_extension(margin_line.RightMargin)
        self.margin_line = settings.SHOW_MARGIN_LINE
        self.margin_line_position = settings.MARGIN_LINE
        self.margin_line_background = settings.MARGIN_LINE_BACKGROUND
        # Indentation guides
        self._indentation_guides = self.register_extension(
            indentation_guides.IndentationGuide)
        self.show_indentation_guides(settings.SHOW_INDENTATION_GUIDES)
        # Autocomplete braces
        self.__autocomplete_braces = self.register_extension(
            braces.AutocompleteBraces)
        self.autocomplete_braces(settings.AUTOCOMPLETE_BRACKETS)
        # Autocomplete quotes
        self.__autocomplete_quotes = self.register_extension(
            quotes.AutocompleteQuotes)
        self.autocomplete_quotes(settings.AUTOCOMPLETE_QUOTES)
        # Mark occurrences timer
        self._highlight_word_timer = QTimer()
        self._highlight_word_timer.setSingleShot(True)
        self._highlight_word_timer.setInterval(800)
        # FIXME
        # self._highlight_word_timer.timeout.connect(
            # self.highlight_selected_word)
        # Install custom scrollbar
        self._scrollbar = scrollbar.NScrollBar(self)
        self._scrollbar.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setVerticalScrollBar(self._scrollbar)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.additional_builtins = None
        # Set the editor after initialization
        if self._neditable is not None:
            if self._neditable.editor:
                self.setDocument(self._neditable.document)
            else:
                self._neditable.set_editor(self)
            self._neditable.checkersUpdated.connect(self._highlight_checkers)
        self.register_syntax_for(language=neditable.language())
        # Widgets on side area
        self.side_widgets = manager.SideWidgetManager(self)
        # Mark text changes
        self._text_change_widget = self.side_widgets.add(
            text_change_widget.TextChangeWidget)
        self.show_text_changes(settings.SHOW_TEXT_CHANGES)
        # Breakpoints/bookmarks widget
        self._marker_area = self.side_widgets.add(
            marker_widget.MarkerWidget)
        # Line number widget
        self._line_number_widget = self.side_widgets.add(
            line_number_widget.LineNumberWidget)
        self.show_line_numbers(settings.SHOW_LINE_NUMBERS)
        # Code folding
        self.side_widgets.add(code_folding.CodeFoldingWidget)

        # FIXME: we need a method to initialize
        self.__set_whitespaces_flags(self.__show_whitespaces)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.blockCountChanged.connect(self.update)

    def autocomplete_braces(self, value):
        self.__autocomplete_braces.actived = value

    def autocomplete_quotes(self, value):
        self.__autocomplete_quotes.actived = value

    def navigate_bookmarks(self, forward=True):
        if forward:
            self._marker_area.next_bookmark()
        else:
            self._marker_area.previous_bookmark()

    def dropEvent(self, event):
        if event.type() == Qt.ControlModifier and self.has_selection:
            insertion_cursor = self.cursorForPosition(event.pos())
            insertion_cursor.insertText(self.selected_text())
        else:
            super().dropEvent(event)

    def set_language(self, language):
        self.register_syntax_for(language=language)
        self._indenter = indenter.load_indenter(self, lang=language)

    def register_syntax_for(self, language="python", force=False):
        syntax = highlighter.build_highlighter(language, force=force)
        if syntax is not None:
            self._highlighter = highlighter.SyntaxHighlighter(
                self.document(), syntax)

    def restyle(self):
        self.__init_style()
        self.__apply_style()
        self.register_syntax_for(force=True)
        self._highlighter.rehighlight()

    def show_line_numbers(self, value):
        self._line_number_widget.setVisible(value)

    def show_text_changes(self, value):
        self._text_change_widget.setVisible(value)

    def font_antialiasing(self, value):
        font = self.default_font
        style = font.PreferAntialias
        if not value:
            style = font.NoAntialias
        font.setStyleStrategy(style)
        self.default_font = font

    def register_extension(self, Extension):
        extension_instance = Extension()
        self.__extensions[Extension.name] = extension_instance
        extension_instance.initialize(self)
        return extension_instance

    def show_indentation_guides(self, value):
        self._indentation_guides.actived = value

    @property
    def indentation_width(self):
        return self._indenter.width

    @indentation_width.setter
    def indentation_width(self, width):
        self._indenter.width = width
        self._update_tab_stop_width()

    @property
    def use_tabs(self):
        return self._indenter.use_tabs

    @use_tabs.setter
    def use_tabs(self, value):
        self._indenter.use_tabs = value

    def move_up_down(self, up=False):
        cursor = self.textCursor()
        move = cursor
        with self:
            has_selection = cursor.hasSelection()
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            if has_selection:
                move.setPosition(start)
                move.movePosition(QTextCursor.StartOfBlock)
                move.setPosition(end, QTextCursor.KeepAnchor)
                m = QTextCursor.EndOfBlock
                if move.atBlockStart():
                    m = QTextCursor.Left
                move.movePosition(m, QTextCursor.KeepAnchor)
            else:
                move.movePosition(QTextCursor.StartOfBlock)
                move.movePosition(QTextCursor.EndOfBlock,
                                  QTextCursor.KeepAnchor)

            text = cursor.selectedText()
            move.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            move.removeSelectedText()

            if up:
                move.movePosition(QTextCursor.PreviousBlock)
                move.insertBlock()
                move.movePosition(QTextCursor.Left)
            else:
                move.movePosition(QTextCursor.EndOfBlock)
                if move.atBlockStart():
                    move.movePosition(QTextCursor.NextBlock)
                    move.insertBlock()
                    move.movePosition(QTextCursor.Left)
                else:
                    move.insertBlock()

            start = move.position()
            move.clearSelection()
            move.insertText(text)
            end = move.position()
            if has_selection:
                move.setPosition(end)
                move.setPosition(start, QTextCursor.KeepAnchor)
            else:
                move.setPosition(start)
            self.setTextCursor(move)

    def duplicate_line(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            cursor_at_start = cursor.position() == start
            cursor.setPosition(end)
            cursor.insertText("\n" + text)
            cursor.setPosition(end if cursor_at_start else start)
            cursor.setPosition(start if cursor_at_start else end,
                               QTextCursor.KeepAnchor)
        else:
            position = cursor.position()
            block = cursor.block()
            text = block.text() + "\n"
            cursor.setPosition(block.position())
            cursor.insertText(text)
            cursor.setPosition(position)
        self.setTextCursor(cursor)

    @property
    def occurrences(self):
        return self.__occurrences

    def adjust_scrollbar_ranges(self):
        line_spacing = QFontMetrics(self.font()).lineSpacing()
        if line_spacing == 0:
            return
        offset = self.contentOffset().y()
        self._scrollbar.set_visible_range(
            (self.viewport().rect().height() - offset) / line_spacing)
        self._scrollbar.set_range_offset(offset / line_spacing)

    def _highlight_checkers(self, neditable):
        """Add checker selections to the Editor"""
        # Remove selections if they exists
        self.clear_extra_selections('checker')
        self._scrollbar.remove_marker("checker")
        # Get checkers from neditable
        checkers = neditable.sorted_checkers
        self.highlight_checker_updated.emit(checkers)

        selections = []
        for items in checkers:
            checker, color, _ = items
            lines = checker.checks.keys()
            for line in lines:
                # Scrollbar marker
                Marker = scrollbar.marker
                marker = Marker(line, color, priority=1)
                self._scrollbar.add_marker("checker", marker)
                # Extra selection
                msg, col = checker.checks[line]
                selection = extra_selection.ExtraSelection(
                    self.textCursor(),
                    start_line=line,
                    offset=col - 1
                )
                selection.set_underline(color)
                selections.append(selection)

        self.add_extra_selections('checker', selections)

    def extra_selections(self, selection_key):
        return self._extra_selections.get(selection_key, [])

    def add_extra_selections(self, selection_key, selections):
        """Adds a extra selection on a editor instance"""
        self._extra_selections[selection_key] = selections
        self.update_extra_selections()

    def clear_extra_selections(self, selection_key):
        """Removes a extra selection from the editor"""
        if selection_key in self._extra_selections:
            self._extra_selections[selection_key] = []
            self.update_extra_selections()

    def update_extra_selections(self):
        extra_selections = []
        for key, selection in self._extra_selections.items():
            extra_selections.extend(selection)
        extra_selections = sorted(extra_selections, key=lambda sel: sel.order)
        self.setExtraSelections(extra_selections)

    def all_extra_selections(self):
        return self._extra_selections

    def allow_word_wrap(self, value):
        wrap_mode = wrap_mode = QPlainTextEdit.NoWrap
        if value:
            wrap_mode = QPlainTextEdit.WidgetWidth
        self.setLineWrapMode(wrap_mode)

    def _update_tab_stop_width(self):
        """Update the tab stop width"""

        width = self.fontMetrics().width(' ') * self._indenter.width
        self.setTabStopWidth(width)

    def clone(self):
        """Returns an instance of the same class and links this
        instance with its original"""

        line, col = self.cursor_position
        clone = self.__class__(self.neditable)
        clone.cursor_position = line, col
        clone.setExtraSelections(self.extraSelections())
        return clone

    def line_count(self):
        """Returns the number of lines"""

        return self.document().blockCount()

    def set_font(self, font):
        """Set font and update tab stop width"""
        QPlainTextEdit.setFont(self, font)
        self.font_antialiasing(settings.FONT_ANTIALIASING)
        self._update_tab_stop_width()

    def line_text(self, line=-1):
        """Returns the text of the specified line.

        :param line: The line number of the text to return.
        :return: Entire lines text.
        :rtype: str.
        """
        if line == -1:
            line, _ = self.cursor_position
        block = self.document().findBlockByNumber(line)
        return block.text()

    @property
    def text(self):
        """Get or set the plain text editor's content. The previous contents
        are removed.

        :param text: Text to set in document.
        :type text: string.
        :return: The plain text in document.
        :rtype: string.
        """

        return self.toPlainText()

    @text.setter
    def text(self, text):
        self.setPlainText(text)

    @pyqtSlot()
    def _on_cursor_position_changed(self):
        self.__clear_occurrences()
        line, col = self.cursor_position
        self.cursor_position_changed.emit(line, col)
        if line != self._last_line_position:
            self._last_line_position = line
            self.current_line_changed.emit(line)
        # Create marker for scrollbar
        self.update_current_line_in_scrollbar(line)
        # Mark occurrences
        self._highlight_word_timer.stop()
        self._highlight_word_timer.start()

    def update_current_line_in_scrollbar(self, current_line):
        """Update current line highlight in scrollbar"""

        self._scrollbar.remove_marker('current_line')
        if self._scrollbar.maximum() > 0:
            Marker = scrollbar.marker
            marker = Marker(current_line, 'white', priority=2)
            self._scrollbar.add_marker('current_line', marker)

    def __init_style(self):
        self._background_color = QColor(
            resources.get_color('EditorBackground'))
        self._foreground_color = QColor(
            resources.get_color('Default'))
        self._selection_color = QColor(
            resources.get_color('EditorSelectionColor'))
        self._selection_background_color = QColor(
            resources.get_color('EditorSelectionBackground'))

    def __apply_style(self):
        palette = self.palette()
        palette.setColor(palette.Base, self._background_color)
        palette.setColor(palette.Text, self._foreground_color)
        palette.setColor(palette.HighlightedText, self._selection_color)
        palette.setColor(palette.Highlight, self._selection_background_color)
        self.setPalette(palette)
        # FIXME: no funciona con qpalette
        # self.setStyleSheet('border: 0px solid transparent;')

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.editorFocusObtained.emit()

    def resizeEvent(self, event):
        QPlainTextEdit.resizeEvent(self, event)
        self.side_widgets.resize()
        self.adjust_scrollbar_ranges()

    def paintEvent(self, event):
        self._update_visible_blocks()
        QPlainTextEdit.paintEvent(self, event)
        # Emit signal for extensions
        self.painted.emit(event)

    def mouseReleaseEvent(self, event):
        # if event.modifiers() == Qt.ControlModifier:
        #    self._code_completion.go_to_definition()
        super().mouseReleaseEvent(event)

    def first_visible_block(self):
        return self.firstVisibleBlock()

    def last_visible_block(self):
        return self.cursorForPosition(
            QPoint(0, self.viewport().height())).block()

    def enable_extension(self, extension_name, value):
        # I'm sure the object always exists
        ext_obj = self.__extensions.get(extension_name)
        if ext_obj is None:
            logger.error("Extension '%s' not found" % extension_name)
        else:
            ext_obj.enabled = value
            # logger.debug("Loaded '%s' extension" % extension_name)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if not settings.SCROLL_WHEEL_ZOMMING:
                return
            delta = event.angleDelta().y() / 120.
            if delta != 0:
                self.zoom(delta)
            return
        QPlainTextEdit.wheelEvent(self, event)

    def mouseMoveEvent(self, event):
        # Restore mouse cursor if settings say hide while typing
        if self.viewport().cursor().shape() == Qt.BlankCursor:
            self.viewport().setCursor(Qt.IBeamCursor)
        '''if event.modifiers() == Qt.ControlModifier:
            if self.__link_selection is not None:
                return
            cursor = self.cursorForPosition(event.pos())
            # Check that the mouse was actually on the text somewhere
            on_text = self.cursorRect(cursor).right() >= event.x()
            if on_text:
                cursor.select(QTextCursor.WordUnderCursor)
                selection_start = cursor.selectionStart()
                selection_end = cursor.selectionEnd()
                self.__link_selection = extra_selection.ExtraSelection(
                    cursor,
                    start_pos=selection_start,
                    end_pos=selection_end
                )
                self.__link_selection.set_underline("red")
                self.__link_selection.set_full_width()
                self.add_extra_selection(self.__link_selection)
                self.viewport().setCursor(Qt.PointingHandCursor)'''
        super(NEditor, self).mouseMoveEvent(event)

    def scroll_step_up(self):
        self.verticalScrollBar().triggerAction(
            QAbstractSlider.SliderSingleStepSub)

    def scroll_step_down(self):
        self.verticalScrollBar().triggerAction(
            QAbstractSlider.SliderSingleStepAdd)

    def text_before_cursor(self, text_cursor=None):
        if text_cursor is None:
            text_cursor = self.textCursor()
        text_block = text_cursor.block().text()
        return text_block[:text_cursor.positionInBlock()]

    def keyReleaseEvent(self, event):
        # if event.key() == Qt.Key_Control:
        #    if self.__link_selection is not None:
        #        self.remove_extra_selection(self.__link_selection)
        #        self.__link_selection = None
        #        self.viewport().setCursor(Qt.IBeamCursor)
        super().keyReleaseEvent(event)

    def keyPressEvent(self, event):
        if settings.HIDE_MOUSE_CURSOR:
            self.viewport().setCursor(Qt.BlankCursor)
        if self.isReadOnly():
            return
        # Emit a signal then plugins can do something
        event.ignore()
        self.keyPressed.emit(event)
        if event.matches(QKeySequence.InsertParagraphSeparator):
            self._indenter.indent_block(self.textCursor())
            return
        if event.key() == Qt.Key_Home:
            self.__manage_key_home(event)
            return
        elif event.key() == Qt.Key_Tab:
            if self.textCursor().hasSelection():
                self._indenter.indent_selection()
            else:
                self._indenter.indent()
            event.accept()
        elif event.key() == Qt.Key_Backspace:
            if not event.isAccepted():
                if self.__smart_backspace():
                    event.accept()
        if not event.isAccepted():
            super().keyPressEvent(event)
        # Post key press
        self.postKeyPressed.emit(event)

    def _auto_indent(self):
        cursor = self.textCursor()
        at_start_of_line = cursor.positionInBlock() == 0
        with self:
            cursor.insertBlock()
            if not at_start_of_line:
                indent = self._indenter.indent_block(cursor.block())
                if indent is not None:
                    cursor.insertText(indent)

    def __smart_backspace(self):
        accepted = False
        cursor = self.textCursor()
        text_before_cursor = self.text_before_cursor(cursor)
        text = cursor.block().text()
        indentation = self._indenter.text()
        space_at_start_len = len(text) - len(text.lstrip())
        column_number = cursor.positionInBlock()
        if text_before_cursor.endswith(indentation) and \
                space_at_start_len == column_number and \
                not cursor.hasSelection():
            to_remove = len(text_before_cursor) % len(indentation)
            if to_remove == 0:
                to_remove = len(indentation)
            cursor.setPosition(cursor.position() - to_remove,
                               QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            accepted = True
        return accepted

    def __manage_key_home(self, event):
        """Performs home key action"""
        cursor = self.textCursor()
        indent = self.line_indent()
        # For selection
        move = QTextCursor.MoveAnchor
        if event.modifiers() == Qt.ShiftModifier:
            move = QTextCursor.KeepAnchor
        # Operation
        if cursor.positionInBlock() == indent:
            cursor.movePosition(QTextCursor.StartOfBlock, move)
        elif cursor.atBlockStart():
            cursor.setPosition(cursor.block().position() + indent, move)
        elif cursor.positionInBlock() > indent:
            cursor.movePosition(QTextCursor.StartOfLine, move)
            cursor.setPosition(cursor.block().position() + indent, move)
        self.setTextCursor(cursor)
        event.accept()

    def __enter__(self):
        self.textCursor().beginEditBlock()

    def __exit__(self, exc_type, exc_value, traceback):
        self.textCursor().endEditBlock()

    def selection_range(self):
        """Returns the start and end number of selected lines"""

        text_cursor = self.textCursor()
        start = self.document().findBlock(
            text_cursor.selectionStart()).blockNumber()
        end = self.document().findBlock(
            text_cursor.selectionEnd()).blockNumber()
        if text_cursor.columnNumber() == 0 and start != end:
            end -= 1
        return start, end

    def _update_visible_blocks(self):
        """Updates the list of visible blocks"""

        self.__visible_blocks = []
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(
            self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        editor_height = self.height()
        while block.isValid():
            visible = bottom <= editor_height
            if not visible:
                break
            if block.isVisible():
                self.__visible_blocks.append((top, block_number, block))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def zoom(self, delta: int):
        font = self.default_font
        previous_point_size = font.pointSize()
        new_point_size = int(max(1, previous_point_size + delta))
        if new_point_size != previous_point_size:
            font.setPointSize(new_point_size)
            self.set_font(font)
            # Emit signal for indicator
            default_point_size = settings.FONT.pointSize()
            percent = new_point_size / default_point_size * 100.0
            self.zoomChanged.emit(percent)
        # Update all side widgets
        self.side_widgets.update_viewport()

    def reset_zoom(self):
        font = self.default_font
        default_point_size = settings.FONT.pointSize()
        if font.pointSize() != default_point_size:
            font.setPointSize(default_point_size)
            self.set_font(font)
            # Emit signal for indicator
            self.zoomChanged.emit(100)
        # Update all side widgets
        self.side_widgets.update_viewport()

    def __set_whitespaces_flags(self, show):
        """Sets white spaces flag"""

        doc = self.document()
        options = doc.defaultTextOption()
        if show:
            options.setFlags(options.flags() | QTextOption.ShowTabsAndSpaces)
        else:
            options.setFlags(options.flags() & ~QTextOption.ShowTabsAndSpaces)
        doc.setDefaultTextOption(options)

    def selected_text(self):
        """Returns the selected text"""

        return self.textCursor().selectedText()

    def has_selection(self):
        return self.textCursor().hasSelection()

    def get_right_word(self):
        """Gets the word on the right of the text cursor"""

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.WordRight, QTextCursor.KeepAnchor)
        return cursor.selectedText().strip()

    def get_right_character(self):
        """Gets the right character on the right of the text cursor"""

        right_word = self.get_right_word()
        right_char = None
        if right_word:
            right_char = right_word[0]
        return right_char

    def is_code(self, cursor):
        user_data = cursor.block().userData()
        if user_data is not None:
            pass

    def line_indent(self, line=-1):
        """Returns the indentation level of `line`"""

        if line == -1:
            line, _ = self.cursor_position
        text = self.document().findBlockByNumber(line).text()
        indentation = len(text) - len(text.lstrip())
        return indentation

    def replace_match(self, word_old, word_new, cs=False, wo=False,
                      wrap_around=True):
        """
        Find if searched text exists and replace it with new one.
        If there is a selection just do it inside it and exit
        """

        cursor = self.textCursor()
        text = cursor.selectedText()
        if not cs:
            word_old = word_old.lower()
            text = text.lower()
        if text == word_old:
            cursor.insertText(word_new)

        # Next
        return self.find_match(word_old, cs, wo, forward=True,
                               wrap_around=wrap_around)

    def replace_all(self, word_old, word_new, cs=False, wo=False):
        # Save cursor for restore later
        cursor = self.textCursor()
        with self:
            # Move to beginning of text and replace all
            self.moveCursor(QTextCursor.Start)
            found = True
            while found:
                found = self.replace_match(word_old, word_new, cs, wo,
                                           wrap_around=False)
        # Reset position
        self.setTextCursor(cursor)

    def find_match(self, search, case_sensitive=False, whole_word=False,
                   backward=False, forward=False, wrap_around=True):

        if not backward and not forward:
            self.moveCursor(QTextCursor.StartOfWord)

        flags = QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QTextDocument.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindWholeWords
        if backward:
            flags |= QTextDocument.FindBackward

        cursor = self.textCursor()
        found = self.document().find(search, cursor, flags)
        if not found.isNull():
            self.setTextCursor(found)

        elif wrap_around:
            if forward:
                cursor.movePosition(QTextCursor.Start)
            else:
                cursor.movePosition(QTextCursor.End)

            # Try again
            found = self.document().find(search, cursor, flags)
            if not found.isNull():
                self.setTextCursor(found)

        return not found.isNull()

    def _get_find_index_results(self, expr, cs, wo):

        text = self.text
        current_index = 0

        if not cs:
            text = text.lower()
            expr = expr.lower()

        if wo:
            expr = r"\b%s\b" % expr

        def find_all_iter(string, sub):
            try:
                reobj = re.compile(sub)
            except sre_constants.error:
                return
            for match in reobj.finditer(string):
                yield match.span()

        matches = list(find_all_iter(text, expr))

        if len(matches) > 0:
            position = self.textCursor().position()
            current_index = sum(1 for _ in re.finditer(expr, text[:position]))
        return current_index, matches

    def show_run_cursor(self):
        """Highlight momentarily a piece of code"""

        cursor = self.textCursor()
        if self.has_selection():
            # Get selection range
            start_pos, end_pos = cursor.selectionStart(), cursor.selectionEnd()
        else:
            # If no selected text, highlight current line
            cursor.movePosition(QTextCursor.StartOfLine)
            start_pos = cursor.position()
            cursor.movePosition(QTextCursor.EndOfLine)
            end_pos = cursor.position()
        # Create extra selection
        selection = extra_selection.ExtraSelection(
            cursor,
            start_pos=start_pos,
            end_pos=end_pos
        )
        selection.set_background("gray")
        self.add_extra_selections("run_cursor", [selection])
        # Clear selection for show correctly the extra selection
        cursor.clearSelection()
        self.setTextCursor(cursor)
        # Remove extra selection after 0.3 seconds
        QTimer.singleShot(
            300, lambda: self.clear_extra_selections("run_cursor"))

    def is_comment(self, block):
        """Check if the block is a inline comment"""

        text_block = block.text().lstrip()
        return text_block.startswith('#')  # FIXME: generalize it

    def __clear_occurrences(self):
        """Clear extra selection occurrences from editor and scrollbar"""

        self.__occurrences.clear()
        self._scrollbar.remove_marker('occurrence')
        self.clear_extra_selections('occurrences')

    def highlight_selected_word(self, word_find=None, results=None, cs=True):
        if results is None:
            word = self._text_under_cursor()
            if word_find is not None:
                word = word_find
            results = self._get_find_index_results(word, cs=cs, wo=True)[1]

        selections = []
        # On very big files where a lots of occurrences can be found,
        # this freeze the editor during a few seconds. So, we can limit of 500
        # and make sure the editor will always remain responsive
        append = selections.append
        results = results[:500]
        for start, end in results:
            selection = extra_selection.ExtraSelection(
                self.textCursor(),
                start_pos=start,
                end_pos=end
            )
            selection.set_full_width()
            selection.set_background(resources.get_color('SearchResult'))
            append(selection)
            # TODO: highlight results in scrollbar
            # line = selection.cursor.blockNumber()
            # Marker = scrollbar.marker
            # marker = Marker(line, resources.get_color("SearchResult"), 0)
            # self._scrollbar.add_marker("find", marker)
        self.add_extra_selections("find", selections)

    def line_from_position(self, position):
        height = self.fontMetrics().height()
        for top, line, block in self.__visible_blocks:
            if top <= position <= top + height:
                return line
        return -1

    def _text_under_cursor(self):
        text_cursor = self.textCursor()
        text_cursor.select(QTextCursor.WordUnderCursor)
        match = re.findall(r'([^\d\W]\w*)', text_cursor.selectedText())
        if match:
            return match[0]

    def go_to_line(self, lineno, column=0, center=True):
        """Go to an specific line

        :param lineno: The line number to go
        :param column: The column number to go
        :param center: If True scrolls the document in order to center the
        cursor vertically.
        :type lineno: int"""

        if self.line_count() >= lineno:
            self.cursor_position = lineno, column
            if center:
                self.centerCursor()
            else:
                self.ensureCursorVisible()
        self.addBackItemNavigation.emit()

    def comment(self):
        pass

    def save_state(self):
        state = {}
        state['vscrollbar'] = self.verticalScrollBar().value()
        return state

    def user_data(self, block=None):
        if block is None:
            block = self.textCursor().block()
        user_data = block.userData()
        if user_data is None:
            user_data = BlockUserData()
            block.setUserData(user_data)
        return user_data


class BlockUserData(QTextBlockUserData):
    """Representation of the data for a block"""

    def __init__(self):
        QTextBlockUserData.__init__(self)
        self.attrs = {}

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def __getitem__(self, name):
        return self.attrs[name]

    def __setitem__(self, name, value):
        self.attrs[name] = value


def create_editor(neditable=None):
    neditor = NEditor(neditable)
    # if neditable is not None:
    #    language = neditable.language()
    #    if language is not None:
    #        neditor.register_syntax_for(language=language)

    return neditor
