"""Every piece of text the user can see, in one place. No Qt.

Templates use str.format with named fields, e.g. SAVE_CHANGES.format(name=...). "&" in menu text marks the
Alt-key letter. Error messages from Python itself (like OSError's strerror) are shown as they come.
"""

APP_NAME = "stemgraph"
VERSION = "0.1.0"  # semantic versioning; the one place the version is defined
UNTITLED = "Untitled"
WINDOW_TITLE = "{name}[*] - {app}"  # [*] is where Qt shows the unsaved-changes marker

# --- Nodes ---

NODE_INPUT = "Input"
NODE_OUTPUT = "Output"
NODE_SPLIT_CENTER_SIDE = "Split Center/Side"
PORT_AUDIO = "audio"
PORT_CENTER = "center"
PORT_SIDE = "side"
NAME_CAPTION = "Name:"
ALGORITHM_CAPTION = "Algorithm:"
ALGORITHM_AUTO = "Auto"
ALGORITHM_PAULUS_TORCOLI = "Paulus–Torcoli"
ALGORITHM_MID_SIDE = "Mid/side"
AUTO_LIST_LABEL = "Auto ({choice})"  # Auto in an opened dropdown, naming what it currently stands for
ALGORITHM_PAULUS_TORCOLI_TIP = "Side output is stereo"
ALGORITHM_MID_SIDE_TIP = "Side output is mono, inverted on the right"
CHOOSE_FILE = "Choose file…"
ADD_NODE_HEADING = "Add Node"

# --- Canvas controls ---

EDIT_MODE_TIP = "Edit mode (V)"
DRAG_MODE_TIP = "Drag mode (H, or hold Space)"
ZOOM_OUT_TIP = "Zoom out (Ctrl+-)"
RESET_ZOOM_TIP = "Reset zoom to 100% (Ctrl+0)"
ZOOM_IN_TIP = "Zoom in (Ctrl+=)"
ZOOM_PERCENT = "{percent}%"
BUILD_BUTTON = "Build"
BUILD_TIP = "Build (Ctrl+B)"

# --- Menus ---

MENU_FILE = "&File"
MENU_NEW = "&New"
MENU_OPEN = "&Open…"
MENU_OPEN_RECENT = "Open &Recent"
MENU_CLEAR_RECENT = "&Clear Recent"
MENU_SAVE = "&Save"
MENU_SAVE_AS = "Save &As…"
MENU_EXIT = "E&xit"
MENU_VIEW = "&View"
MENU_ZOOM_IN = "Zoom &In"
MENU_ZOOM_OUT = "Zoom &Out"
MENU_ACTUAL_SIZE = "&100%"
MENU_ZOOM_TO_FIT = "Zoom to &Fit"
MENU_EDIT_MODE = "&Edit Mode"
MENU_DRAG_MODE = "&Drag Mode"
MENU_BUILD_ACTION = "&Build…"
RECENT_ITEM = "{number} {name}"
RECENT_ITEM_FOLDER = "{name} ({folder})"  # when two recent projects have the same name
MENU_HELP = "&Help"
MENU_ABOUT = "&About"

# --- Start window and About ---

VERSION_LABEL = "Version {version}"
START_NEW = "New"
START_OPEN = "Open…"
START_RECENT_HEADING = "Recent"
NO_RECENT = "No recent projects."
# Rich text: {license} is a link to the license
CREDITS = "stemgraph © 2026 Julian Lachniet. Licensed under the {license}."
LICENSE_NAME = "GNU General Public License v3.0"
ABOUT_THIRD_PARTY_HEADING = "Third-party credits"
# Rich text: {qt}, {numpy} etc. open a link (to the URL of that name in welcome.py) and {end} closes it.
#
# How to write a credit:
# - A library, font, icon set or other asset goes in THIRD_PARTY_SOFTWARE, in alphabetical order of its name (as
#   shown, ignoring case): its name, linked to its home page, then its license, e.g. "{numpy}NumPy{end}, BSD
#   license". Name a bundled part the same way: "..., with {libsndfile}libsndfile{end}, LGPL v2.1". There's no
#   formal standard for this; it's the usual short form of an About screen.
# - A paper goes in THIRD_PARTY_PAPERS, ordered by the first author's surname, then by year. Write what stemgraph
#   uses from it, in the paper's own words and in sentence case, then "from", then the paper's IEEE citation
#   exactly as IEEE Xplore's "Cite This" > IEEE button gives it for the published version (not a preprint). That
#   is, with every field copied unchanged from the DOI's record (https://api.crossref.org/works/<doi>):
#       <initial>. <surname> and <initial>. <surname>, "<title>," <venue>, <location>, <year>, pp. <pages>, doi: <doi>.
#   (three or more authors: "A, B and C"; a journal article: "<journal>, vol. <v>, no. <n>, pp. <pages>,
#   <month> <year>, doi: <doi>."). Link the title (inside the quotation marks) to the paper's free arXiv page,
#   https://arxiv.org/abs/<id>, or to https://doi.org/<doi> if it isn't on arXiv.
THIRD_PARTY_SOFTWARE = [
    "{numpy}NumPy{end}, BSD license",
    "{soundfile}python-soundfile{end}, BSD license, with {libsndfile}libsndfile{end}, LGPL v2.1",
    "{qt}Qt for Python{end} (PySide6), LGPL v3",
    "{radix_icons}Radix Icons{end} and {radix_colors}Radix Colors{end}, MIT license",
]
THIRD_PARTY_PAPERS = [
    'Center-channel extraction from J. Paulus and M. Torcoli, "{paper}Geometrically-Motivated Primary-Ambient '
    'Decomposition With Center-Channel Extraction{end}," 2022 30th European Signal Processing Conference '
    "(EUSIPCO), Belgrade, Serbia, 2022, pp. 299-303, doi: 10.23919/EUSIPCO55093.2022.9909879.",
]
THIRD_PARTY = THIRD_PARTY_SOFTWARE + THIRD_PARTY_PAPERS
ABOUT_OK = "OK"

# --- File dialogs ---

OPEN_PROJECT_TITLE = "Open Project"
SAVE_PROJECT_TITLE = "Save Project As"
PROJECT_FILTER = "stemgraph Project Files (*{extension})"
ALL_FILES_FILTER = "All Files (*)"
CHOOSE_AUDIO_TITLE = "Choose Audio File"
AUDIO_FILES_FILTER = "Audio Files ({patterns})"
EXPORT_FOLDER_TITLE = "Export To"

# --- Project files ---

SAVE_CHANGES = "Save changes to {name}?"
DONT_SAVE = "Don't Save"
PROJECT_NOT_FOUND = "{file} couldn't be found.\n\n{path}"
CANT_OPEN = "Couldn't open {file}.\n\n{reason}"
CANT_SAVE = "Couldn't save {file}.\n\n{reason}"
NOT_A_PROJECT_OR_DAMAGED = "The file isn't a stemgraph project, or it is damaged."
NOT_A_PROJECT = "The file isn't a stemgraph project."
NEWER_VERSION = "The file was saved by a newer version of stemgraph."
INVALID_VALUE = "The file contains an invalid value."
INVALID_NODE = "The file contains an invalid node."
INVALID_CONNECTION = "The file contains an invalid connection."
UNKNOWN_NODE = "The file contains an unknown type of node: {type}."

# --- Audio files ---

AUDIO_UNREADABLE = "{file} couldn't be read as audio."
AUDIO_TOO_MANY_CHANNELS = "{file} has too many channels: (has {channels}, expected 1 or 2)"

# --- Before building ---

CANT_BUILD_YET = "The project couldn't be built:\n\n{problems}"
PROBLEM_ITEM = "• {problem}"
NOTHING_TO_BUILD = "No output nodes are present"
OUTPUT_NOT_CONNECTED = 'Output "{output}" has nothing connected to it.'
NODE_NOT_CONNECTED = "A {node} node has nothing connected to its input."
INPUT_NO_FILE = 'Input "{input}" has no file chosen.'
INPUT_PROBLEM = 'Input "{input}": {problem}'
INPUT_FILE_NOT_FOUND = "{file} couldn't be found."
NUMBERED_NAME = "{name} {number}"  # a default Output name already taken: "Song center 2"
OUTPUT_NAME_TOO_LONG = 'Output "{output}" has a name too long for a file name.'
OUTPUTS_CLASH = 'Outputs "{first}" and "{second}" would both be saved as {file}.'
REPLACE_ONE = "This file already exists in the export folder:\n\n{files}\n\nReplace it?"
REPLACE_MANY = "These files already exist in the export folder:\n\n{files}\n\nReplace them?"
REPLACE_ITEM = "    {file}"
REPLACE_BUTTON = "Replace"

# --- Building ---

PROGRESS_TITLE = "Building {name}"
STEP_COUNT = "Step {done}/{total}"
STARTING = "Starting…"
OPEN_FOLDER = "Open Folder"
DONE = "Done"
CANCELLED = "Cancelled"
BUILD_FAILED = "Build failed"
CANCELLING = "Cancelling after this step…"

STEP_LOAD = "Loading {file}"
STEP_RESAMPLE = "Resampling {file} from {rate} Hz to {target} Hz"
STEP_SPLIT = "Splitting {source} into center and side"
STEP_WRITE = "Writing {file}"
SOURCE_OUTPUT = "{source} {port}"  # a split's output, as a source: "Song center"

LOG_MONO = "{file} is mono; using it on both channels."
LOG_PEAK = "{file} peaks at +{db:.1f} dBFS."
LOG_CANCELLED = "Cancelled. No files were written."
LOG_DONE_ONE = "Done. Wrote 1 file to {folder}."
LOG_DONE_MANY = "Done. Wrote {count} files to {folder}."
CANT_WRITE_FILE = "Couldn't write {file}: {reason}."
CANT_WRITE_FOLDER = "Couldn't write to the export folder: {reason}."
NO_MEMORY_LOAD = "There isn't enough memory to load {file}."
NO_MEMORY_RESAMPLE = "There isn't enough memory to resample {file}."
NO_MEMORY_SPLIT = "There isn't enough memory to split {source}."
NO_MEMORY_BUILD = "There isn't enough memory to finish the build."
