import sublime, sublime_plugin
import re, itertools

last_index = 0
hints = []
search_regex = r''

next_search = False

# MODES
# 0: default (jumps in front of the selection)
# 1: select
# 2: add-cursor
# 3: jump-after
mode = 0

ace_jump_active = False

# Labels defined in setting file
ace_jump_labels = []

# Labels generated dynamically
ace_jump_active_labels = []

def get_active_views(window, current_buffer_only):
    """Returns all currently visible views"""

    views = []
    if current_buffer_only:
        views.append(window.active_view())
    else:
        for group in range(window.num_groups()):
            views.append(window.active_view_in_group(group))
    return views

def set_views_setting(views, setting, values):
    """Sets the values for the setting in all given views"""

    for i in range(len(views)):
        views[i].settings().set(setting, values[i])

def set_views_settings(views, settings, values):
    """Sets the values for all settings in all given views"""

    for i in range(len(settings)):
        set_views_setting(views, settings[i], values[i])

def get_views_setting(views, setting):
    """Returns the setting value for all given views"""

    settings = []
    for view in views:
        settings.append(view.settings().get(setting))
    return settings

def get_views_settings(views, settings):
    """Gets the settings for every given view"""

    values = []
    for setting in settings:
        values.append(get_views_setting(views, setting))
    return values

def set_views_syntax(views, syntax):
    """Sets the syntax highlighting for all given views"""

    for i in range(len(views)):
        views[i].set_syntax_file(syntax[i])

def set_views_sel(views, selections):
    """Sets the selections for all given views"""

    for i in range(len(views)):
        for sel in selections[i]:
            views[i].sel().add(sel)

def get_views_sel(views):
    """Returns the current selection for each from the given views"""

    selections = []
    for view in views:
        selections.append(view.sel())
    return selections
    
def sort_double_char_labels(labels):
    """Sort double char labels based on the order of repeated, lower and other labels"""
    repeated_char_labels = [label for label in labels if label[0] == label[1]]

    lower_char_labels = [label for label in labels
                         if label[0].islower() and label[1].islower()
                         and label not in repeated_char_labels]

    other_labels = [label for label in labels
                    if label not in repeated_char_labels and label not in lower_char_labels]

    labels = repeated_char_labels + lower_char_labels + other_labels

    return labels

class AceJumpCommand(sublime_plugin.WindowCommand):
    """Base command class for AceJump plugin"""

    def run(self, current_buffer_only = False):
        global ace_jump_active
        ace_jump_active = True

        global ace_jump_labels
        ace_jump_labels = []

        self.char = ""
        self.target = ""
        self.views = []
        self.changed_views = []
        self.breakpoints = []

        self.all_views = get_active_views(self.window, current_buffer_only)
        self.syntax = get_views_setting(self.all_views, "syntax")
        self.sel = get_views_sel(self.all_views)

        settings = sublime.load_settings("AceJump.sublime-settings")
        self.highlight = settings.get("labels_scope", "invalid")
        self.labels = settings.get(
            "labels",
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        ace_jump_labels = self.labels
        self.double_char_label = settings.get("double_char_label", False)
        self.jump_to_boundary = settings.get("jump_to_boundary", True)
        self.case_sensitivity = settings.get("search_case_sensitivity", True)
        self.jump_behind_last = settings.get("jump_behind_last_characters", False)
        self.save_files_after_jump = settings.get("save_files_after_jump", False)

        self.view_settings = settings.get("view_settings", [])
        self.view_values = get_views_settings(
            self.all_views,
            self.view_settings
        )

        self.show_prompt(self.prompt(), self.init_value())

    def is_enabled(self):
        global ace_jump_active
        return not ace_jump_active

    def show_prompt(self, title, value):
        """Shows a prompt with the given title and value in the window"""

        self.window.show_input_panel(
            title, value,
            self.next_batch, self.on_input, self.submit
        )

    def next_batch(self, command):
        """Displays the next batch of labels after pressing return"""

        self.remove_labels()
        self.show_prompt(self.prompt(), self.char)

    def on_input(self, command):
        """Fires the necessary actions for the current input"""

        global ace_jump_active_labels

        if len(command) == 0:
            self.add_labels(self.regex())
            return

        if ace_jump_active_labels and len(command) == 2:
            self.target = command
            self.labels = ace_jump_active_labels
            self.window.run_command("hide_panel", {"cancel": True})

    def submit(self):
        """Handles the behavior after closing the prompt"""
        global next_search, mode, ace_jump_active
        next_search = False

        self.remove_labels()
        set_views_sel(self.all_views, self.sel)
        set_views_syntax(self.all_views, self.syntax)

        if self.valid_target(self.target):
            self.jump(self.get_index(self.target, self.labels))

        mode = 0
        ace_jump_active = False

        """Saves changed views after jump is complete"""
        if self.save_files_after_jump:
          for view in self.changed_views:
            if not view.is_read_only() and not view.is_dirty():
              view.run_command("save")

    def add_labels(self, regex):
        """Adds labels to characters matching the regex"""

        global last_index, hints

        last_index = 0
        hints = []

        self.views = self.views_to_label()
        self.region_type = self.get_region_type()
        self.changed_views = []
        self.breakpoints = []
        changed_buffers = []

        for view in self.views[:]:
            if view.buffer_id() in changed_buffers:
                break

            view.run_command("add_ace_jump_labels", {
                "regex": regex,
                "region_type": self.region_type,
                "labels": self.labels,
                "double_char_label": self.double_char_label,
                "highlight": self.highlight,
                "case_sensitive": self.case_sensitivity
            })
            self.breakpoints.append(last_index)
            self.changed_views.append(view)
            changed_buffers.append(view.buffer_id())

            if next_search:
                break

            self.views.remove(view)

        set_views_syntax(self.all_views, list(itertools.repeat(
            "Packages/AceJump/AceJump.tmLanguage",
            len(self.all_views)
        )))

        set_views_settings(
            self.all_views,
            self.view_settings,
            self.view_values
        )

    def remove_labels(self):
        """Removes all previously added labels"""

        last_breakpoint = 0
        for breakpoint in self.breakpoints:
            if breakpoint != last_breakpoint:
                view = self.changed_views[self.view_for_index(breakpoint - 1)]
                view.run_command("remove_ace_jump_labels")
                last_breakpoint = breakpoint

    def jump(self, index):
        """Performs the jump action"""

        region = hints[index].begin()
        view = self.changed_views[self.view_for_index(index)]

        self.window.focus_view(view)
        view.run_command("perform_ace_jump", {"target": region, 
                                              "jump_to_boundary": self.jump_to_boundary})
        self.after_jump(view)

    def views_to_label(self):
        """Returns the views that still have to be labeled"""

        if mode != 0:
            return [self.window.active_view()]

        return self.all_views[:] if len(self.views) == 0 else self.views

    def view_for_index(self, index):
        """Returns a view index for the given label index"""

        for breakpoint in self.breakpoints:
            if index < breakpoint:
                return self.breakpoints.index(breakpoint)

    def valid_target(self, target):
        """Check if jump target is valid"""
        index = self.get_index(target, self.labels)
        return target != "" and index >= 0 and index < last_index;

    def get_region_type(self):
        """Return region type for labeling"""

        return "visible_region"

    def get_index(self, item, sequence):
        """Return label index in str or list label set"""
        if isinstance(sequence, str):
            index = sequence.find(item)
        elif isinstance(sequence, list):
            index = sequence.index(item)
        return index

class AceJumpWordCommand(AceJumpCommand):
    """Specialized command for word-mode"""

    def prompt(self):
        return "Jump Target"

    def init_value(self):
        return ""

    def regex(self):
        return r'(\b\w+)'

    def after_jump(self, view):
        global mode

        if mode == 3:
            view.run_command("move", {"by": "word_ends", "forward": True})
            mode = 0

class AceJumpCharCommand(AceJumpCommand):
    """Specialized command for char-mode"""

    def prompt(self):
        return "Char"

    def init_value(self):
        return ""

    def regex(self):
        return r'([a-zA-Z])..'

    def after_jump(self, view):
        global mode

        if mode == 3:
            view.run_command("move", {"by": "characters", "forward": True})
            mode = 0

    def jump(self, index):
        global mode

        view = self.changed_views[self.view_for_index(index)]
        if self.jump_behind_last and "\n" in view.substr(hints[index].end()):
            mode = 3

        return AceJumpCommand.jump(self, index)

# class AceJumpLineCommand(AceJumpCommand):
#     """Specialized command for line-mode"""

#     def prompt(self):
#         return ""

#     def init_value(self):
#         return " "

#     def regex(self):
#         return r'(.*)[^\s](.*)\n'

#     def after_jump(self, view):
#         global mode

#         if mode == 3:
#             view.run_command("move", {"by": "lines", "forward": True})
#             view.run_command("move", {"by": "characters", "forward": False})
#             mode = 0

# class AceJumpWithinLineCommand(AceJumpCommand):
#     """Specialized command for within-line-mode"""

#     def prompt(self):
#         return ""

#     def init_value(self):
#         return " "

#     def regex(self):
#         return r'\b\w|\w\b|(?<=_)\w|\w(?=_)'

#     def after_jump(self, view):
#         global mode

#         if mode == 3:
#             view.run_command("move", {"by": "word_ends", "forward": True})
#             mode = 0

#     def get_region_type(self):

#         return "current_line"

# class AceJumpSelectCommand(sublime_plugin.WindowCommand):
#     """Command for turning on select mode"""

#     def run(self):
#         global mode

#         mode = 0 if mode == 1 else 1

# class AceJumpAddCursorCommand(sublime_plugin.WindowCommand):
#     """Command for turning on multiple cursor mode"""

#     def run(self):
#         global mode

#         mode = 0 if mode == 2 else 2

class AceJumpAfterCommand(sublime_plugin.WindowCommand):
    """Modifier-command which lets you jump behind a character, word or line"""

    def run(self):
        global mode

        mode = 0 if mode == 3 else 3

class AddAceJumpLabelsCommand(sublime_plugin.TextCommand):
    """Command for adding labels to the views"""

    # Regions after label replacing
    replaced_regions = []

    def run(self, edit, regex, region_type, labels, double_char_label, highlight, case_sensitive):
        global hints

        max_labels = len(labels) ** 2 if double_char_label else len(labels)
        characters = self.find(regex, region_type, max_labels, case_sensitive)
        self.add_labels(edit, characters, labels, double_char_label)
        # self.view.add_regions("ace_jump_hints", characters, highlight)
        self.view.add_regions("ace_jump_hints", self.replaced_regions, highlight)

        hints = hints + characters

    def find(self, regex, region_type, max_labels, case_sensitive):
        """Returns a list with all occurences matching the regex"""

        global next_search, last_index

        chars = []

        region = self.get_target_region(region_type)
        next_search = next_search if next_search else region.begin()
        last_search = region.end()

        while (next_search < last_search and last_index < max_labels):
            word = self.view.find(regex, next_search, 0 if case_sensitive else sublime.IGNORECASE)

            if not word or word.end() >= last_search:
                break

            last_index += 1
            next_search = word.end()
            chars.append(sublime.Region(word.begin(), word.begin() + 1))

        if last_index < max_labels:
            next_search = False

        return chars

    def add_labels(self, edit, regions, labels, double_char_label):
        """Replaces the given regions with labels"""

        global ace_jump_active_labels

        if double_char_label and len(regions) > len(labels):
            labels = [char_a + char_b for char_a in labels for char_b in labels]
            labels = sort_double_char_labels(labels)
            for i, region in enumerate(regions):
                regions[i] = sublime.Region(region.a, region.b + 1)

        ace_jump_active_labels = labels

        num_region = len(regions)
        region_offset = 0
        self.replaced_regions = []

        for i in range(len(regions)):
            label = labels[last_index + i - num_region]
            region = regions[i]
            if region_offset:
                region = sublime.Region(region.a + region_offset, region.b + region_offset)
            content = self.view.substr(region)
            if content[-1] in ('\n', '\r'):
                # region = sublime.Region(region.a, region.b + 1)
                label += content[-1]
                region_offset += 1
            self.replaced_regions.append(region)
            self.view.replace(edit, region, label)

    def get_target_region(self, region_type):

        return {
            'visible_region': lambda view : view.visible_region(),
            'current_line': lambda view : view.line(view.sel()[0]),
        }.get(region_type)(self.view)

class RemoveAceJumpLabelsCommand(sublime_plugin.TextCommand):
    """Command for removing labels from the views"""

    def run(self, edit):
        self.view.erase_regions("ace_jump_hints")
        self.view.end_edit(edit)
        self.view.run_command("undo")

class PerformAceJumpCommand(sublime_plugin.TextCommand):
    """Command performing the jump"""

    def run(self, edit, target, jump_to_boundary):
        global mode
        if mode == 0 or mode == 3:
            self.view.sel().clear()

        self.view.sel().add(self.target_region(target, jump_to_boundary))
        self.view.show(target)

    def target_region(self, target, jump_to_boundary):
        if jump_to_boundary:
            # Check if the target next to boundary, if so, move the target one letter righter to put the 
            # cursor right on the boundary
            nextChar = self.view.substr(sublime.Region(target + 1, target + 2))
            if re.match('[^\w]', nextChar):
                target += 1

        if mode == 1:
            for cursor in self.view.sel():
                return sublime.Region(cursor.begin(), target)

        return sublime.Region(target)