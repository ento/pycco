#!/usr/bin/env python

"""
"**Pycco**" is a Python port of [Docco](http://jashkenas.github.com/docco/):
the original quick-and-dirty, hundred-line-long, literate-programming-style
documentation generator. It produces HTML that displays your comments
alongside your code. Comments are passed through
[Markdown](http://daringfireball.net/projects/markdown/syntax) and
[SmartyPants](http://daringfireball.net/projects/smartypants), while code is
passed through [Pygments](http://pygments.org/) for syntax highlighting.
This page is the result of running Pycco against its own source file.

If you install Pycco, you can run it from the command-line:

    pycco src/*.py

This will generate linked HTML documentation for the named source files,
saving it into a `docs` folder by default.

The [source for Pycco](https://github.com/fitzgen/pycco) is available on GitHub,
and released under the MIT license.

To install Pycco, simply

    pip install pycco

Or, to install the latest source

    git clone git://github.com/fitzgen/pycco.git
    cd pycco
    python setup.py install
"""


renderer_flavors = {
    'markdown': {
        'multistart': '```',
        'multiend': '```',
    }
}
default_render_opts = {'name': 'markdown', 'kwargs': {}}
renderers = {}


try:
    from markdown import markdown
    renderers['markdown'] = {
        'func': markdown,
        'flavor': 'markdown',
        'defaults': {
            'extensions': ['fenced_code', 'attr_list'],
        },
    }
except ImportError:
    pass

try:
    from markdown2 import markdown
    renderers['markdown2'] = {
        'func': markdown,
        'flavor': 'markdown',
        'defaults': {
            'extras': ['fenced-code-block'],
        },
    }
except ImportError:
    pass

try:
    import misaka
    def preprocess_misaka_kwargs(kwargs):
        for key in ('extensions', 'render_flags'):
            kwargs[key] = reduce(operator.or_, [getattr(misaka, attr) for attr in kwargs.pop(key, [])], 0)
        return kwargs
    renderers['misaka'] = {
        'func': misaka.html,
        'preprocess_kwargs': preprocess_misaka_kwargs,
        'flavor': 'markdown',
        'defaults': {
            'extensions': ['EXT_FENCED_CODE'],
        },
    }
except ImportError:
    pass


for name, renderer in renderers.iteritems():
    renderer.update(renderer_flavors[renderer['flavor']])


def prepare_renderer(render_opts):
    renderer = renderers[render_opts['name']]
    render_func = renderer['func']
    kwargs = dict(renderer['defaults'], **render_opts['kwargs'])

    if renderer.get('preprocess_kwargs'):
        kwargs = renderer['preprocess_kwargs'](kwargs)
    
    def render(source):
        return render_func(source, **kwargs)

    return {
        'func': render,
        'multistart': renderer['multistart'],
        'multiend': renderer['multiend'],
    }


default_renderer = prepare_renderer(default_render_opts)


# === Main Documentation Generation Functions ===

def generate_translations(source, destination, language=None, renderer=default_renderer):
    """
    Generate side-by-side translations for a source document by reading it in,
    listing up translations in the same directory, splitting them
    up into sections and merging them into an HTML template.
    """

    text = codecs.open(source, "r", "utf8").read()
    source_doc = parse(source, text, language=language, renderer=renderer)
    highlight(source, source_doc, renderer, destination)
    for translation in get_translations(source):
        text = codecs.open(translation, "r", "utf8").read()
        translated_doc = parse(translation, text, language=language, renderer=renderer)
        highlight(translation, translated_doc, renderer, destination)
        doc = merge_docs(source_doc, translated_doc)
        yield translation, generate_html(source, translation, doc, destination)


def parse(source, text, language=None, renderer=default_renderer):
    """
    Given a string of text, determine the title and split the rest into **section**s.
    Sections take the form:

        { "text": ...,
          "html": ...,
          "num":  ...
        }
    """
    language = get_language(source, text, language=language)

    lines = text.split("\n")
    sections = []
    chunk = ''

    if lines[0].startswith("#!"):
        lines.pop(0)

    def save(chunk):
        if chunk:
            sections.append({
                "text": chunk,
            })

    title = lines.pop(0)

    # Setup the variables to get ready to check for multiline chunks
    multi_line = False
    multi_line_delimiters = [renderer.get("multistart"), renderer.get("multiend")]

    for line in lines:
        if all(multi_line_delimiters) and any([line.lstrip().startswith(delim) or line.rstrip().endswith(delim) for delim in multi_line_delimiters]):
            if not multi_line:
                multi_line = True
            else:
                multi_line = False

            if (multi_line
               and line.strip().endswith(renderer.get("multiend"))
               and len(line.strip()) > len(renderer.get("multiend"))):
                multi_line = False

            # Get rid of the delimiters so that they aren't in the
            # final docs
            if renderer.get("strip_multi_delimiters"):
                line = line.replace(renderer["multistart"], '')
                line = line.replace(renderer["multiend"], '')

            if not multi_line:
                chunk += '\n' + line

            if chunk:
                save(chunk)
                chunk = ''

            if multi_line:
                chunk += line

        elif multi_line:
            chunk += '\n' + line
        elif line:
            chunk += '\n' + line
        else:
            save(chunk)
            chunk = ''

    save(chunk)
    return {'title': title, 'sections': sections, 'language': language}


def merge_docs(source_doc, translation_doc):
    doc = {
        'source_title': source_doc['title'],
        'translation_title': translation_doc['title'],
        'source_language': source_doc['language'],
        'translation_language': translation_doc['language'],
        'sections': []}
    get_html = lambda section: (section or {}).get('html', '')
    for i, (source_section, translation_section) in enumerate(itertools.izip_longest(source_doc['sections'], translation_doc['sections'])):
        doc['sections'].append(dict(
            num=i,
            source_html=get_html(source_section),
            translation_html=get_html(translation_section)))
    return doc


# === Preprocessing the comments ===

def preprocess(comment, section_nr, destination):
    """
    Add cross-references before having the text processed by markdown.  It's
    possible to reference another file, like this : `[[main.py]]` which renders
    [[main.py]]. You can also reference a specific section of another file, like
    this: `[[main.py#highlighting-the-source-code]]` which renders as
    [[main.py#highlighting-the-source-code]]. Sections have to be manually
    declared; they are written on a single line, and surrounded by equals signs:
    `=== like this ===`
    """

    def sanitize_section_name(name):
        return "-".join(name.lower().strip().split(" "))

    def replace_crossref(match):
        # Check if the match contains an anchor
        if '#' in match.group(1):
            name, anchor = match.group(1).split('#')
            return " [%s](%s#%s)" % (name,
                                     path.basename(destination(name)),
                                     anchor)

        else:
            return " [%s](%s)" % (match.group(1),
                                  path.basename(destination(match.group(1))))

    def replace_section_name(match):
        return '%(lvl)s <span id="%(id)s" href="%(id)s">%(name)s</span>' % {
            "lvl"  : re.sub('=', '#', match.group(1)),
            "id"   : sanitize_section_name(match.group(2)),
            "name" : match.group(2)
        }

    comment = re.sub('^([=]+)([^=]+)[=]*\s*$', replace_section_name, comment)
    comment = re.sub('[^`]\[\[(.+?)\]\]', replace_crossref, comment)

    return comment

# === Highlighting the source code ===

def highlight(source, doc, renderer, destination):
    """
    Highlights a single chunk of code using the **Pygments** module, and runs
    the text of its corresponding comment through **Markdown**.

    We process the entire file in a single call to Pygments by inserting little
    marker comments between each section and then splitting the result string
    wherever our markers occur.
    """

    for i, section in enumerate(doc['sections']):
        try:
            text = unicode(section["text"])
        except UnicodeError:
            text = unicode(section["text"].decode('utf-8'))
        preprocessed = preprocess(text, i, destination)
        section["html"] = renderer['func'](preprocessed)
        section["num"] = i

# === HTML Code generation ===

def generate_html(source, translation, doc, destination):
    """
    Once all of the section is merged, we can generate the HTML file
    and write out the translation. Pass the completed sections into the
    template found in `resources/pycco.html`.

    Pystache will attempt to recursively render context variables, so we must
    replace any occurences of `{{`, with a "unique enough" identifier before
    rendering, and then post-process the rendered template and change the
    identifier back to `{{`.
    """

    dest = destination(source)
    csspath = path.relpath(destination("pycco.css", override_ext=None), path.split(dest)[0])

    for sect in doc['sections']:
        for key in ('source_html', 'translation_html'):
            sect[key] = re.sub(r"\{\{", r"__DOUBLE_OPEN_STACHE__", sect[key])

    context = {
        "stylesheet"  : csspath,
        "source"      : source,
        "path"        : path,
        "destination" : dest
    }
    context.update(doc)
    rendered = pycco_template(context)

    return re.sub(r"__DOUBLE_OPEN_STACHE__", "{{", rendered).encode("utf-8")

# === Helpers & Setup ===

# This module contains all of our static resources.
import pycco_resources

# Import our external dependencies.
import optparse
import os
import codecs
import itertools
import json
import glob
import operator
import pystache
import re
import sys
import time
from os import path
from babel import Locale


def get_language(source, code, language=None):
    """Get the source language, based on the basename."""

    if language is not None:
        locale = Locale.parse(language)
        if locale:
            return locale.language
        else:
            raise ValueError("Unknown forced language: " + language)

    m = re.match(r'(.*)(\..+)', os.path.basename(source))
    if m:
        locale = Locale.parse(m.group(1))
        if locale:
            return locale.language
    raise ValueError("Can't figure out the language!")


def get_translations(source):
    return [filepath for filepath in glob.iglob(os.path.join(os.path.dirname(source), '*.md')) if filepath != source]


def destination(filepath, preserve_paths=True, strip_paths=0, outdir=None, override_ext='.html'):
    """
    Compute the destination HTML path for an input source file path. If the
    source is `lib/example.py`, the HTML will be at `docs/example.html`
    """

    dirname, filename = path.split(filepath)
    if not outdir:
        raise TypeError("Missing the required 'outdir' keyword argument.")
    name = filename
    if override_ext:
        try:
            name = re.sub(r"\.[^.]*$", override_ext, filename)
        except ValueError:
            pass
    if preserve_paths:
        name = path.join(os.sep.join(dirname.split(os.sep)[strip_paths:]), name)
    return path.join(outdir, name)

def shift(list, default):
    """
    Shift items off the front of the `list` until it is empty, then return
    `default`.
    """

    try:
        return list.pop(0)
    except IndexError:
        return default

def ensure_directory(directory):
    """Ensure that the destination directory exists."""

    if not os.path.isdir(directory):
        os.makedirs(directory)

def template(source):
    return lambda context: pystache.render(source, context)

# Create the template that we will use to generate the Pycco HTML page.
pycco_template = template(pycco_resources.html)

# The CSS styles we'd like to apply to the documentation.
pycco_styles = pycco_resources.css


def process(sources, preserve_paths=True, strip_paths=0, outdir=None, language=None, render_opts=default_render_opts):
    """For each source file passed as argument, generate the documentation."""

    if not outdir:
        raise TypeError("Missing the required 'outdir' keyword argument.")

    # Make a copy of sources given on the command line. `main()` needs the
    # original list when monitoring for changed files.
    sources = sorted(sources)

    # Proceed to generating the documentation.
    if sources:
        def get_destination(source, **kwargs):
            return destination(source, preserve_paths=preserve_paths, strip_paths=strip_paths, outdir=outdir, **kwargs)

        ensure_directory(outdir)
        css = open(get_destination("pycco.css", override_ext=None), "w")
        css.write(pycco_styles)
        css.close()

        renderer = prepare_renderer(render_opts)

        def next_file():
            s = sources.pop(0)
            dest = get_destination(s)
            try:
                os.makedirs(path.split(dest)[0])
            except OSError:
                pass

            for filepath, translation in generate_translations(
                    s,
                    destination=get_destination,
                    language=language,
                    renderer=renderer):
                dest = get_destination(filepath)
                with open(dest, "w") as f:
                    f.write(translation)

                print "pycco = %s -> %s" % (s, dest)

            if sources:
                next_file()
        next_file()

__all__ = ("process", "generate_translations")


def monitor(sources, opts):
    """Monitor each source file and re-generate documentation on change."""

    # The watchdog modules are imported in `main()` but we need to re-import
    # here to bring them into the local namespace.
    import watchdog.events
    import watchdog.observers

    # Watchdog operates on absolute paths, so map those to original paths
    # as specified on the command line.
    absolute_sources = dict((os.path.abspath(source), source)
                            for source in sources)

    class RegenerateHandler(watchdog.events.FileSystemEventHandler):
        """A handler for recompiling files which triggered watchdog events"""
        def on_modified(self, event):
            """Regenerate documentation for a file which triggered an event"""
            # Re-generate documentation from a source file if it was listed on
            # the command line. Watchdog monitors whole directories, so other
            # files may cause notifications as well.
            if event.src_path in absolute_sources:
                process([absolute_sources[event.src_path]],
                        outdir=opts.outdir,
                        preserve_paths=opts.paths)

    # Set up an observer which monitors all directories for files given on
    # the command line and notifies the handler defined above.
    event_handler = RegenerateHandler()
    observer = watchdog.observers.Observer()
    directories = set(os.path.split(source)[0] for source in sources)
    for directory in directories:
        observer.schedule(event_handler, path=directory)

    # Run the file change monitoring loop until the user hits Ctrl-C.
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()


def main():
    """Hook spot for the console script."""

    def to_json(option, _, value, parser):
        return setattr(parser.values, option.dest, json.loads(value))

    parser = optparse.OptionParser()
    parser.add_option('-p', '--paths', action='store_true',
                      default=False,
                      help='Preserve path structure of original files')

    parser.add_option('--strip-paths NUM', type='int',
                      dest='strip_paths', default=0,
                      help='When preserving path, strip NUM path components from the beginning of original files')

    parser.add_option('-d', '--directory', action='store', type='string',
                      dest='outdir', default='docs',
                      help='The output directory that the rendered files should go to.')

    parser.add_option('-w', '--watch', action='store_true',
                      help='Watch original files and re-generate documentation on changes')

    parser.add_option('-s', '--source-language', action='store', type='string',
                      dest='language', default=None,
                      help='Default source language')

    parser.add_option('-r', '--renderer-name', action='store', type='string',
                      dest='renderer_name', default=default_render_opts['name'],
                      help='Text rendering engine')

    parser.add_option('--renderer-opts', action='callback', type='string', callback=to_json,
                      dest='renderer_opts', default=default_render_opts['kwargs'],
                      help='Additional kwargs in JSON to pass to the text rendering engine')
    opts, sources = parser.parse_args()

    process(sources, outdir=opts.outdir, preserve_paths=opts.paths, strip_paths=opts.strip_paths,
            language=opts.language, render_opts={'name': opts.renderer_name, 'kwargs': opts.renderer_opts})

    # If the -w / --watch option was present, monitor the source directories
    # for changes and re-generate documentation for source files whenever they
    # are modified.
    if opts.watch:
        try:
            import watchdog.events
            import watchdog.observers
        except ImportError:
            sys.exit('The -w/--watch option requires the watchdog package.')

        monitor(sources, opts)

# Run the script.
if __name__ == "__main__":
    main()
