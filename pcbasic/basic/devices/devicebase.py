"""
PC-BASIC - devicebase.py
Devices, Files and I/O operations

(c) 2013--2018 Rob Hagemans
This file is released under the GNU GPL version 3 or later.
"""

import io
import os
import struct
import logging
from contextlib import contextmanager

from ..base import error
from ..base.eascii import as_bytes as ea
from .. import values

def nullstream():
    return open(os.devnull, b'r+')


# magic chars used by some devices to indicate file type
TYPE_TO_MAGIC = { b'B': b'\xFF', b'P': b'\xFE', b'M': b'\xFD' }
MAGIC_TO_TYPE = { b'\xFF': b'B', b'\xFE': b'P', b'\xFD': b'M' }



############################################################################
# Device classes
#
#  Some devices have a master file, where newly opened files inherit
#  width (and other?) settings from this file
#  For example, WIDTH "SCRN:", 40 works directly on the console,
#  whereas OPEN "SCRN:" FOR OUTPUT AS 1: WIDTH #1,23 works on the wrapper file
#  but does ot affect other files on SCRN: nor the console itself.
#  Likewise, WIDTH "LPT1:" works on LLIST etc and on lpt1 for the next time it's opened.


############################################################################

def parse_protocol_string(arg):
    """Retrieve protocol and options from argument."""
    if not arg:
        return None, u''
    argsplit = arg.split(u':', 1)
    if len(argsplit) == 1:
        addr, val = None, argsplit[0]
    else:
        addr, val = argsplit[0].upper(), u''.join(argsplit[1:])
    return addr, val


class NullDevice(object):
    """Null device (NUL) """

    def __init__(self):
        """Set up device."""

    def open(self, number, param, filetype, mode, access, lock,
                   reclen, seg, offset, length, field):
        """Open a file on the device."""
        return TextFileBase(nullstream(), filetype, mode)

    def close(self):
        """Close the device."""

    def available(self):
        """Device is available."""
        return True


class Device(object):
    """Device interface for master-file devices."""

    allowed_modes = ''

    def __init__(self):
        """Set up device."""
        self.device_file = None

    def open(
            self, number, param, filetype, mode, access, lock,
            reclen, seg, offset, length, field):
        """Open a file on the device."""
        if not self.device_file:
            raise error.BASICError(error.DEVICE_UNAVAILABLE)
        if mode not in self.allowed_modes:
            raise error.BASICError(error.BAD_FILE_MODE)
        new_file = self.device_file.open_clone(filetype, mode, reclen)
        return new_file

    def close(self):
        """Close the device."""
        if self.device_file:
            self.device_file.close()

    def available(self):
        """Device is available."""
        return True


class SCRNDevice(Device):
    """Screen device (SCRN:) """

    allowed_modes = 'OR'

    def __init__(self, display):
        """Initialise screen device."""
        # open a master file on the screen
        Device.__init__(self)
        self.device_file = SCRNFile(display)

    def open(
            self, number, param, filetype, mode, access, lock,
            reclen, seg, offset, length, field):
        """Open a file on the device."""
        new_file = Device.open(
                self, number, param, filetype, mode, access, lock,
                reclen, seg, offset, length, field)
        # SAVE "SCRN:" includes a magic byte
        new_file.write(TYPE_TO_MAGIC.get(filetype, b''))
        return new_file

class KYBDDevice(Device):
    """Keyboard device (KYBD:) """

    allowed_modes = 'IR'

    def __init__(self, keyboard, display):
        """Initialise keyboard device."""
        # open a master file on the keyboard
        Device.__init__(self)
        self.device_file = KYBDFile(keyboard, display)


#################################################################################
# file classes

# file interface:
#   __enter__(self)
#   __exit__(self, exc_type, exc_value, traceback)
#   close(self)
#   input_chars(self, num)
#   read(self, num=-1)
#   write(self, s)
#   filetype
#   mode


class DeviceSettings(object):
    """Device-level settings, not a file as such."""

    def __init__(self):
        """Setup the basic properties of the file."""
        self.width = 255
        self.col = 1

    def set_width(self, width):
        """Set file width."""
        self.width = width

    def close(self):
        """Close dummy device file."""


@contextmanager
def safe_io():
    """Catch and translate I/O errors."""
    try:
        yield
    except EnvironmentError as e:
        logging.warning('I/O error on stream access: %s', e)
        raise error.BASICError(error.DEVICE_IO_ERROR)


class RawFile(object):
    """File class for raw access to underlying stream."""

    def __init__(self, fhandle, filetype, mode):
        """Setup the basic properties of the file."""
        self._fhandle = fhandle
        self.filetype = filetype
        self.mode = mode.upper()

    def __enter__(self):
        """Context guard."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context guard."""
        self.close()

    def close(self):
        """Close the file."""
        with safe_io():
            self._fhandle.close()

    def input_chars(self, num):
        """Read a number of characters."""
        with safe_io():
            return self._fhandle.read(num)

    def read(self, num=-1):
        """Read num chars. If num==-1, read all available."""
        with safe_io():
            return self._fhandle.read(num)

    def write(self, s):
        """Write string to file."""
        with safe_io():
            self._fhandle.write(s)


#################################################################################
# Text file base

# text interface: file interface (except read) +
#   col
#   width
#   read_line(self)
#   write_line(self, s='')
#   eof(self)
#   set_width(self, new_width=255)
#   input_entry(self, typechar, allow_past_end)
#   lof(self)
#   loc(self)
#
#   internal use: read_one()


class TextFileBase(RawFile):
    """Base for text files on disk, KYBD file, field buffer."""

    def __init__(self, fhandle, filetype, mode, first_char=''):
        """Setup the basic properties of the file."""
        RawFile.__init__(self, fhandle, filetype, mode)
        # width=255 means line wrap
        self.width = 255
        self.col = 1
        # allow first char to be specified (e.g. already read)
        self.next_char = first_char
        # Random files are derived from text files and start in 'I' operating mode
        if self.mode in b'IR' and not first_char:
            try:
                self.next_char = self._fhandle.read(1)
            except (EnvironmentError, ValueError):
                # only catching ValueError here because that's what Serial raises
                self.next_char = b''
        self.char, self.last = b'', b''

    def input_chars(self, num):
        """Read num characters as string."""
        s = []
        while True:
            if (num > -1 and len(s) >= num):
                break
            # check for \x1A (EOF char will actually stop further reading
            # (that's true in disk text files but not on COM devices)
            if self.next_char in ('\x1a', ''):
                break
            s.append(self.next_char)
            with safe_io():
                self.next_char, self.char, self.last = (
                        self._fhandle.read(1), self.next_char, self.char)
        return b''.join(s)

    def read(self, num=-1):
        """Stubbed out read()."""
        raise NotImplementedError()

    def read_one(self):
        """Read one character, converting device line ending to b'\r', EOF to b''."""
        return self.input_chars(1)

    def read_line(self):
        """\
            Read a single line until line break or 255 characters.
            Output line and line break character
            Return None for CR if line ended due to 255-char length limit
            Return '' for CR if EOF
        """
        out = []
        while True:
            c = self.read_one()
            # don't check for CRLF on KYBD:, CAS:, etc.
            if not c or c == b'\r':
                break
            out.append(c)
            if len(out) == 255:
                c = b'\r' if self.next_char == b'\r' else None
                break
        return b''.join(out), c

    def write(self, s, can_break=True):
        """Write the string s to the file, taking care of width settings."""
        # only break lines at the start of a new string. width 255 means unlimited width
        s_width = 0
        newline = False
        # find width of first line in s
        for c in str(s):
            if c in (b'\r', b'\n'):
                newline = True
                break
            if ord(c) >= 32:
                # nonprinting characters including tabs are not counted for WIDTH
                s_width += 1
        if can_break and self.width != 255 and self.col != 1 and self.col-1 + s_width > self.width and not newline:
            self.write_line()
            self.col = 1
        for c in s:
            # don't replace CR or LF with CRLF when writing to files
            if c in ('\r',):
                self._fhandle.write(c)
                self.col = 1
            else:
                self._fhandle.write(c)
                # nonprinting characters including tabs are not counted for WIDTH
                if ord(c) >= 32:
                    self.col += 1
                    # col-1 is a byte that wraps
                    if self.col == 257:
                        self.col = 1

    def write_line(self, s=''):
        """Write string and follow with CR or CRLF."""
        self.write(s + b'\r')

    def eof(self):
        """Check for end of file EOF."""
        # for EOF(i)
        if self.mode in (b'A', b'O'):
            return False
        return self.next_char in (b'', b'\x1a')

    def set_width(self, new_width=255):
        """Set file width."""
        self.width = new_width

    # support for INPUT#

    # TAB x09 is not whitespace for input#. NUL \x00 and LF \x0a are.
    whitespace_input = b' \0\n'
    # numbers read from file can be separated by spaces too
    soft_sep = b' '

    def _skip_whitespace(self, whitespace):
        """Skip spaces and line feeds and NUL; return last whitespace char """
        c = b''
        while self.next_char and self.next_char in whitespace:
            # drop whitespace char
            c = self.read_one()
            # LF causes following CR to be dropped
            if c == b'\n' and self.next_char == b'\r':
                # LFCR: drop the CR, report as LF
                self.read_one()
        return c

    def input_entry(self, typechar, allow_past_end):
        """Read a number or string entry for INPUT """
        word, blanks = b'', b''
        # fix readahead buffer (self.next_char)
        last = self._skip_whitespace(self.whitespace_input)
        # read first non-whitespace char
        c = self.read_one()
        # LF escapes quotes
        # may be true if last == '', hence "in ('\n', '\0')" not "in '\n0'"
        quoted = (c == b'"' and typechar == values.STR and last not in (b'\n', b'\0'))
        if quoted:
            c = self.read_one()
        # LF escapes end of file, return empty string
        if not c and not allow_past_end and last not in (b'\n', b'\0'):
            raise error.BASICError(error.INPUT_PAST_END)
        # we read the ending char before breaking the loop
        # this may raise FIELD OVERFLOW
        while c and not ((typechar != values.STR and c in self.soft_sep) or
                        (c in b',\r' and not quoted)):
            if c == b'"' and quoted:
                # whitespace after quote will be skipped below
                break
            elif c == b'\n' and not quoted:
                # LF, LFCR are dropped entirely
                c = self.read_one()
                if c == b'\r':
                    c = self.read_one()
                continue
            elif c == b'\0':
                # NUL is dropped even within quotes
                pass
            elif c in self.whitespace_input and not quoted:
                # ignore whitespace in numbers, except soft separators
                # include internal whitespace in strings
                if typechar == values.STR:
                    blanks += c
            else:
                word += blanks + c
                blanks = b''
            if len(word) + len(blanks) >= 255:
                break
            if not quoted:
                c = self.read_one()
            else:
                # no CRLF replacement inside quotes.
                c = self.input_chars(1)
        # if separator was a whitespace char or closing quote
        # skip trailing whitespace before any comma or hard separator
        if c and c in self.whitespace_input or (quoted and c == b'"'):
            self._skip_whitespace(b' ')
            if (self.next_char in b',\r'):
                c = self.read_one()
        # file position is at one past the separator char
        return word, c


#################################################################################
# Console INPUT


class InputTextFile(TextFileBase):
    """Handle INPUT from console."""

    # spaces do not separate numbers on console INPUT
    soft_sep = b''

    def __init__(self, line):
        """Initialise InputStream."""
        TextFileBase.__init__(self, io.BytesIO(line), b'D', b'I')


#################################################################################
# Console files

def input_entry_realtime(self, typechar, allow_past_end):
    """Read a number or string entry from KYBD: or COMn: for INPUT#."""
    word, blanks = b'', b''
    if self._input_last:
        c, self._input_last = self._input_last, b''
    else:
        c = self.read_one()
    # LF escapes quotes
    quoted = (c == b'"' and typechar == values.STR)
    if quoted:
        c = self.read_one()
    # LF escapes end of file, return empty string
    if not c and not allow_past_end:
        raise error.BASICError(error.INPUT_PAST_END)
    # on reading from a KYBD: file, control char replacement takes place
    # which means we need to use read_one() not input_chars()
    parsing_trail = False
    while c and not (c in b',\r' and not quoted):
        if c == b'"' and quoted:
            parsing_trail = True
        elif c == b'\n' and not quoted:
            # LF, LFCR are dropped entirely
            c = self.read_one()
            if c == b'\r':
                c = self.read_one()
            continue
        elif c == b'\0':
            # NUL is dropped even within quotes
            pass
        elif c in self.whitespace_input and not quoted:
            # ignore whitespace in numbers, except soft separators
            # include internal whitespace in strings
            if typechar == values.STR:
                blanks += c
        else:
            word += blanks + c
            blanks = b''
        if len(word) + len(blanks) >= 255:
            break
        # there should be KYBD: control char replacement here even if quoted
        c = self.read_one()
        if parsing_trail:
            if c not in self.whitespace_input:
                if c not in (b',', b'\r'):
                    self._input_last = c
                break
        parsing_trail = parsing_trail or (typechar != values.STR and c == b' ')
    # file position is at one past the separator char
    return word, c


###############################################################################

class KYBDFile(TextFileBase):
    """KYBD device: keyboard."""

    # replace some eascii codes with control characters
    _input_replace = {
        ea.HOME: b'\xFF\x0B', ea.UP: b'\xFF\x1E', ea.PAGEUP: b'\xFE',
        ea.LEFT: b'\xFF\x1D', ea.RIGHT: b'\xFF\x1C', ea.END: b'\xFF\x0E',
        ea.DOWN: b'\xFF\x1F', ea.PAGEDOWN: b'\xFE',
        ea.DELETE: b'\xFF\x7F', ea.INSERT: b'\xFF\x12',
        ea.F1: b'', ea.F2: b'', ea.F3: b'', ea.F4: b'', ea.F5: b'',
        ea.F6: b'', ea.F7: b'', ea.F8: b'', ea.F9: b'', ea.F10: b'',
        }

    col = 0

    def __init__(self, keyboard, display):
        """Initialise keyboard file."""
        # use mode = 'A' to avoid needing a first char from nullstream
        TextFileBase.__init__(self, nullstream(), filetype=b'D', mode=b'A')
        # buffer for the separator character that broke the last INPUT# field
        # to be attached to the next
        self._input_last = b''
        self._keyboard = keyboard
        # screen needed for width settings on KYBD: master file
        self._display = display
        # on master-file devices, this is the master file.
        self._is_master = True

    def open_clone(self, filetype, mode, reclen=128):
        """Clone device file."""
        inst = KYBDFile(self._keyboard, self._display)
        inst.mode = mode
        inst.reclen = reclen
        inst.filetype = filetype
        inst._is_master = False
        return inst

    def input_chars(self, num):
        """Read a number of characters (INPUT$)."""
        chars = b''
        while len(chars) < num:
            chars += b''.join(b'\0' if c in self._input_replace else c if len(c) == 1 else b''
                              for c in self._keyboard.read_bytes_kybd_file(num-len(chars)))
        return chars

    def read_one(self):
        """Read a character with line ending replacement (INPUT and LINE INPUT)."""
        chars = b''
        while len(chars) < 1:
            # note that we need string length, not list length
            # as read_bytes_kybd_file can return multi-byte eascii codes
            chars += b''.join(self._input_replace.get(c, c)
                              for c in self._keyboard.read_bytes_kybd_file(1))
        return chars

    def lof(self):
        """LOF for KYBD: is 1."""
        return 1

    def loc(self):
        """LOC for KYBD: is 0."""
        return 0

    def eof(self):
        """KYBD only EOF if ^Z is read."""
        if self.mode in (b'A', b'O'):
            return False
        # blocking peek
        return (self._keyboard.peek_byte_kybd_file() == b'\x1a')

    def set_width(self, new_width=255):
        """Setting width on KYBD device (not files) changes screen width."""
        if self._is_master:
            self._display.set_width(new_width)

    input_entry = input_entry_realtime


###############################################################################

class SCRNFile(RawFile):
    """SCRN: file, allows writing to the screen as a text file.
        SCRN: files work as a wrapper text file."""

    def __init__(self, display):
        """Initialise screen file."""
        RawFile.__init__(self, nullstream(), filetype=b'D', mode=b'O')
        # need display object as WIDTH can change graphics mode
        self._display = display
        # screen member is public, needed by print_
        self.screen = display.text_screen
        self._width = self.screen.mode.width
        self._col = self.screen.current_col
        # on master-file devices, this is the master file.
        self._is_master = True

    def open_clone(self, filetype, mode, reclen=128):
        """Clone screen file."""
        inst = SCRNFile(self._display)
        inst.mode = mode
        inst.reclen = reclen
        inst.filetype = filetype
        inst._is_master = False
        return inst

    def write(self, s, can_break=True):
        """Write string s to SCRN: """
        # writes to SCRN files should *not* be echoed
        do_echo = self._is_master
        self._col = self.screen.current_col
        # take column 80+overflow into account
        if self.screen.overflow:
            self._col += 1
        # only break lines at the start of a new string. width 255 means unlimited width
        s_width = 0
        newline = False
        # find width of first line in s
        for c in str(s):
            if c in (b'\r', b'\n'):
                newline = True
                break
            if c == b'\b':
                # for lpt1 and files, nonprinting chars are not counted in LPOS; but chr$(8) will take a byte out of the buffer
                s_width -= 1
            elif ord(c) >= 32:
                # nonprinting characters including tabs are not counted for WIDTH
                s_width += 1
        if can_break and (self.width != 255 and self.screen.current_row != self.screen.mode.height
                and self.col != 1 and self.col-1 + s_width > self.width and not newline):
            self.screen.write_line(do_echo=do_echo)
            self._col = 1
        cwidth = self.screen.mode.width
        for c in str(s):
            if self.width <= cwidth and self.col > self.width:
                self.screen.write_line(do_echo=do_echo)
                self._col = 1
            if self.col <= cwidth or self.width <= cwidth:
                self.screen.write(c, do_echo=do_echo)
            if c in (b'\n', b'\r'):
                self._col = 1
            else:
                self._col += 1

    def write_line(self, inp=b''):
        """Write a string to the screen and follow by CR."""
        self.write(inp)
        self.screen.write_line(do_echo=self._is_master)

    @property
    def col(self):
        """Return current (virtual) column position."""
        if self._is_master:
            return self.screen.current_col
        else:
            return self._col

    @property
    def width(self):
        """Return (virtual) screen width."""
        if self._is_master:
            return self._display.mode.width
        else:
            return self._width

    def set_width(self, new_width=255):
        """Set (virtual) screen width."""
        if self._is_master:
            self._display.set_width(new_width)
        else:
            self._width = new_width

    def lof(self):
        """LOF: bad file mode."""
        raise error.BASICError(error.BAD_FILE_MODE)

    def loc(self):
        """LOC: bad file mode."""
        raise error.BASICError(error.BAD_FILE_MODE)

    def eof(self):
        """EOF: bad file mode."""
        raise error.BASICError(error.BAD_FILE_MODE)
