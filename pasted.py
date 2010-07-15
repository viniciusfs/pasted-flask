"""
    Pasted is a simple pastebin clone using Flask and SQLite.
    Copyright (c) 2010 by Vinicius Figueiredo <viniciusfs@gmail.com>
"""

import sqlite3
import re
import datetime
import hashlib
import difflib

from flask import Flask, request, session, g, redirect, url_for, abort, \
     render_template, flash, Response
from contextlib import closing



# Configuration
SECRET_KEY = '2MvichMhMk0LvIik'
DATABASE = 'db/pasted.db'
DEBUG = True

URLS_LIMIT = 5
URLS_PERCENTAGE = 10

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.debug = DEBUG



def connect_db():
    """Returns a new connection to the database."""
    return sqlite3.connect(DATABASE)


def init_db():
    """Creates database tables."""
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql') as f:
            db.cursor().executescript(f.read())
        db.commit()


def query_db(query, args=(), one=False):
    """Queries database and returns a list of dictionaries."""
    cur = g.db.execute(query, args)
    rv = [dict((cur.description[idx][0], value)
               for idx, value in enumerate(row)) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv


@app.before_request
def before_request():
    """Make sure we are connected to database after each request."""
    g.db = connect_db()


@app.after_request
def after_request(response):
    """Closes the database at the end of request."""
    g.db.close()
    return response


def is_spam(code):
    """Cheks if `code` is spam based on really simple rules."""
    urlfind = re.compile("[A-Za-z]+://.*?")
    urls = urlfind.findall(code)
    url_count = len(urls)

    if url_count > URLS_LIMIT:
        return True
    else:
        word_count = len(code.split())
        urls_percentage = (url_count * 100) / word_count

        if urls_percentage > URLS_PERCENTAGE:
            return True
        else:
            return False


def calc_md5(code):
    """Returns MD5 hash for given `code`."""
    md5 = hashlib.md5()
    md5.update(code)
    return md5.hexdigest()


def create_udiff(original, new):
    """Creates an unified diff comparing `original` and `new`."""
    udiff = difflib.unified_diff(
        original['code'].splitlines(),
        new['code'].splitlines(),
        fromfile='Paste #%d' % original['id'],
        tofile='Paste #%d' % new['id'],
        lineterm='',
        n=4)
    udiff = '\n'.join(udiff)
    return udiff


def render_udiff(udiff):
    """Renders a unified diff into a pretty dictionary.

    Code stolen from LodgeIt:
    http://dev.pocoo.org/projects/lodgeit/browser/lodgeit/lib/diff.py
    """
    change_pattern = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

    lines = udiff.splitlines()
    line_iter = iter(lines)

    mods = {}

    try:
        line = line_iter.next()
        mods['old'] = line[4:]
        line = line_iter.next()
        mods['new'] = line[4:]

        mods['lines'] = []

        line = line_iter.next()

        while True:
            match = change_pattern.match(line)
            if match is not None:
                old_line, old_end, new_line, new_end = [int(x or 1) for x in match.groups()]
                old_line -= 1
                new_line -= 1
                old_end += old_line
                new_end += new_line

                line = line_iter.next()

                while old_line < old_end or new_line < new_end:
                    old_change = new_change = False
                    command, content = line[0], line[1:]

                    if command == ' ':
                        old_change = new_change = True
                        action = 'none'
                    elif command == '-':
                        old_change = True
                        action = 'del'
                    elif command == '+':
                        new_change = True
                        action = 'add'

                    old_line += old_change
                    new_line += new_change

                    mods['lines'].append({
                        'old_line': old_change and old_line or u'',
                        'new_line': new_change and new_line or u'',
                        'action': action,
                        'content': content
                        })

                    line = line_iter.next()
    except StopIteration:
        pass

    return mods


@app.route('/')
def index():
    """Index page."""
    return render_template('form.html', original=None)


@app.route('/view/<paste_id>')
@app.route('/view/<paste_id>/<mode>')
def view(paste_id, mode=None):
    """View snippets with id equals `paste_id` on given `mode`. Possible
    values for `mode` are `None` (default HTML view) and `raw` (text/plain view)."""
    paste = query_db('select * from pasted where id = ?', [paste_id], one=True)

    if paste is None:
        flash('Paste not found!')
        return redirect(url_for('index'))

    viewed_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    g.db.execute('update pasted set viewed_at = ? where id = ?',
                 [viewed_at, paste_id])
    g.db.commit()

    if mode == 'raw':
        return Response(paste['code'], mimetype='text/plain')

    return render_template('view.html', paste=paste)


@app.route('/add', methods=['POST'])
@app.route('/reply/add', methods=['POST'])
@app.route('/reply/<paste_id>', methods=['GET'])
def add_paste(paste_id=None):
    """Adds new snippets to database."""
    if request.method == 'GET':
        paste = query_db('select * from pasted where id = ?', [paste_id],
                         one=True)
        if paste is None:
            flash('Paste not found!')
            return redirect(url_for('index'))

        return render_template('form.html', original=paste)

    if request.form['code'].strip() == '':
        flash('Empty paste!')
        return redirect(url_for('index'))

    if is_spam(request.form['code']) is True:
        flash('Your paste seems to be spam, sorry!')
        return redirect(url_for('index'))

    hexdigest = calc_md5(request.form['code'])

    paste = query_db('select * from pasted where md5 = ?', [hexdigest],
                     one=True)

    if paste is not None:
        return render_template('view.html', paste=paste)

    viewed_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    cur = g.db.execute('insert into pasted (code, md5, viewed_at, parent) values (?, ?, ?, ?)', [request.form['code'], hexdigest, viewed_at, request.form['parent']])
    g.db.commit()
    paste_id = cur.lastrowid
    paste = query_db('select * from pasted where id = ?', [paste_id], one=True)

    return render_template('view.html', paste=paste)


@app.route('/diff/<parent_id>/<paste_id>')
@app.route('/diff/<parent_id>/<paste_id>/<mode>')
def diff(parent_id, paste_id, mode=None):
    """Manages snippets comparison."""
    parent = query_db('select * from pasted where id = ?', [parent_id], one=True)
    paste = query_db('select * from pasted where id = ?', [paste_id], one=True)

    if parent is None or paste is None:
        flash('Pastes not found!')
        return redirect(url_for('index'))

    diff = create_udiff(parent, paste)

    if mode == 'raw':
        return Response(diff, mimetype='text/plain')

    diff = render_udiff(diff)

    return render_template('diff.html', parent=parent, paste=paste, diff=diff)


@app.route('/latest')
def latest_pastes():
    """Shows latest 10 snippets."""
    latest = query_db('select * from pasted order by id desc limit 10')
    return render_template('latest.html', pastes=latest)



if __name__ == '__main__':
    app.run()
