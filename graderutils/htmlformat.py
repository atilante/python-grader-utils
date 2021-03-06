"""
Functions for parsing TestResult objects into HTML.
Uses Jinja2 for template rendering.
"""
import collections
import itertools
import re

import jinja2

from graderutils.main import GraderUtilsError


class HTMLFormatError(GraderUtilsError): pass


def suffix_after(string, split_at):
    """Return suffix of string after first occurrence of split_at."""
    return string.split(split_at, 1)[-1]


def prefix_before(string, split_at):
    """Return prefix of string before first occurrence of split_at."""
    return string.split(split_at, 1)[0]


def collapse_max_recursion_exception(string, repeat_threshold=20):
    """Replace identical lines in a max recursion error traceback
    with a message and the amount lines removed."""
    # Well this turned out to be quite awful.
    result = []
    repeats = 0
    previous_repeat_count = 0
    found_lines = set()
    is_repeating = False
    for line in string.splitlines():
        if line in found_lines:
            repeats += 1
        else:
            if is_repeating:
                found_lines = set()
                previous_repeat_count = repeats
            repeats = 0
            found_lines.add(line)
        if repeats > repeat_threshold:
            # Continue until we find an unique line
            is_repeating = True
            continue
        if is_repeating:
            is_repeating = False
            # TODO localize message
            msg = (
                2*"\n   .    " +
                "\n   .    \n"
                "\n  and {0} more hidden lines\n".format(previous_repeat_count) +
                2*"\n   .    " +
                "\n   .    \n\n"
            )
            result.append(msg)
        result.append(line + '\n')
    return ''.join(result)


def collapse_traceback(traceback_string):
    if re.search(r"RecursionError|MemoryError", traceback_string):
        traceback_string = collapse_max_recursion_exception(traceback_string)
    return traceback_string


def hide_exception_traceback(traceback_string, exception_names, left_strip_fields, replacement_string):
    """
    Find all tracebacks caused by exceptions specified in exception_names and return a string where all traceback occurrences in traceback_string have been replaced with replacement_string.
    In other words, everything starting with 'Traceback (most recent call last)' up until the exception message is replaced.
    If left_strip_fields is larger than 0, then left_strip_fields count of fields separated with ':' will be dropped from the beginning of the exception message.
    E.g. with 2:
    "AssertionError : True is not False : no it isn't" -> "no it isn't"
    """
    traceback_header = "Traceback (most recent call last)"
    # Pattern starting at the traceback header and ending in any of the given exception names, spanning multiple lines
    pattern_hide = re.compile(
        ('^' + re.escape(traceback_header)
         + r'(.|[\n\r])*?' # Non-greedy match of all possible characters
         + '(' + '|'.join('^' + re.escape(e) for e in exception_names) + ')'),
        re.MULTILINE
    )
    # Append the captured exception name from the second capture group
    replacement_string_with_exc_class = replacement_string + r"\2"
    # Remove tracebacks
    traceback_string = re.sub(pattern_hide, replacement_string_with_exc_class, traceback_string)
    # Remove default fields from the beginning of the exception message, if specified
    if left_strip_fields > 0:
        # Matches at most left_strip_fields count of fields separated by ':'
        fields_pattern = "([^:]*?:){," + str(left_strip_fields) + "}\s?"
        pattern_hide = re.compile(
            '(' + '|'.join('^' + re.escape(replacement_string + e) + fields_pattern for e in exception_names) + ')',
            re.MULTILINE
        )
        traceback_string = re.sub(pattern_hide, '', traceback_string)
    return traceback_string


def parsed_assertion_message(assertion_error_traceback, split_at=None):
    """
    Remove traceback and 'AssertionError: ' starting from assertion_error_traceback.
    Optionally split the resulting string at split_at and return the prefix.
    """
    without_traceback = suffix_after(assertion_error_traceback, "AssertionError: ")
    if split_at:
        without_traceback = prefix_before(without_traceback, split_at)
    return without_traceback


ParsedTestResult = collections.namedtuple("ParsedTestResult",
        ("test_outcome", "method_name",
         "assertion_message", "user_data",
         "full_traceback"))


def test_result_as_template_context(result_object, exceptions_to_hide):
    """Return the attribute values from result_object that are needed for HTML template rendering in a dictionary.
    @param (PointsResultObject) Result object from running PointsTestRunner. Expected to contain attributes:
        errors,
        failures,
        testsRun,
        successes,
        stream,
        points,
        max_points,
        test_description,
    @param (dict) Exceptions for which traceback should be replaced with a given string.
    @return (dict) Context dictionary for HTML rendering.
    """
    def _hide_exception_traceback(s):
        return hide_exception_traceback(s,
                exceptions_to_hide["class_names"],
                exceptions_to_hide.get("left_strip_fields", 0),
                exceptions_to_hide.get("replacement_string", ''))

    if not exceptions_to_hide:
        _hide_exception_traceback = lambda s: s

    # Create generators for all result types

    successes = (ParsedTestResult("SUCCESS",
                    test_case.shortDescription(),
                    "",
                    getattr(test_case, "user_data", None),
                    "")
                 for test_case in result_object.successes)

    failures = (ParsedTestResult("FAIL",
                    test_case.shortDescription(),
                    _hide_exception_traceback(full_assert_msg),
                    getattr(test_case, "user_data", None),
                    "")
                for test_case, full_assert_msg in result_object.failures)

    # Tests which had exceptions other than AssertionError
    errors = (ParsedTestResult("ERROR",
                   test_case.shortDescription(),
                   collapse_traceback(_hide_exception_traceback(full_traceback)),
                   getattr(test_case, "user_data", None),
                   _hide_exception_traceback(full_traceback))
              for test_case, full_traceback in result_object.errors)

    # Evaluate all generators into a single list
    results = list(itertools.chain(successes, failures, errors))

    # Get unittest console output from the StringIO instance
    unittest_output = result_object.stream.getvalue()

    # Hide tracebacks (if any are specified)
    unittest_output = _hide_exception_traceback(unittest_output)

    context = {
        "results": results,
        "test_key": result_object.test_key,
        "test_description": result_object.test_description,
        "points": result_object.points,
        "max_points": result_object.max_points,
        "tests_run": result_object.testsRun,
        "unittest_output": unittest_output
    }

    return context


def _load_template(loader, name):
    return jinja2.Environment(loader=loader).get_template(name)

def _load_template_file(name):
    file_loader = jinja2.FileSystemLoader("./")
    return _load_template(file_loader, name)

def _load_package_template(name):
    package_loader = jinja2.PackageLoader("graderutils", "static")
    return _load_template(package_loader, name)


# TODO undry with no_tests_html and no_default_css
def test_results_as_html(results, custom_template_name=None, no_default_css=False, exceptions_to_hide=None):
    """Render the list of results as HTML and return the HTML as a string.
    @param results List of TestResult objects.
    @return Raw HTML as a string.
    """
    result_context_dicts = []
    total_points = total_max_points = total_tests_run = 0

    for res in results:
        result_context = test_result_as_template_context(res, exceptions_to_hide)
        result_context_dicts.append(result_context)
        total_points += result_context["points"]
        total_max_points += result_context["max_points"]
        total_tests_run += result_context["tests_run"]

    context = {
        "all_results": result_context_dicts,
        "total_points": total_points,
        "total_max_points": total_max_points,
        "total_tests_run": total_tests_run,
        "no_default_css": no_default_css
    }

    package_loader = jinja2.PackageLoader("graderutils", "static")
    env = jinja2.Environment(loader=package_loader)
    default_template = env.get_template("feedback_template.html")

    if custom_template_name:
        custom_template = _load_template_file(custom_template_name)
        context["feedback_template"] = default_template
        return custom_template.render(**context)

    return default_template.render(**context)


def no_tests_html(feedback_template=None, no_default_css=False):
    """
    Trivial test result feedback when there are no tests.
    Renders feedback_template with 'no_tests' set to True and returns the raw HTML.
    """
    if feedback_template is None:
        feedback_template = "feedback_template.html"
        template_loader = jinja2.PackageLoader("graderutils", "static")
    else:
        template_loader = jinja2.FileSystemLoader("./")

    env = jinja2.Environment(loader=template_loader)
    template = env.get_template(feedback_template)

    return template.render(no_tests=True, no_default_css=no_default_css)


def errors_as_html(error_data, error_template=None, no_default_css=False):
    """
    Renders the context dictionary errors as html using the given error template and returns the raw html string.
    """
    if error_template is None:
        error_template = "error_template.html"
        template_loader = jinja2.PackageLoader("graderutils", "static")
    else:
        template_loader = jinja2.FileSystemLoader("./")

    env = jinja2.Environment(loader=template_loader)
    template = env.get_template(error_template)
    return template.render(errors=error_data, no_default_css=no_default_css)


def wrap_div_alert(string):
    """Wrap an error message in a red box."""
    return r"<div class='alert alert-danger'>{}</div>".format(string)


