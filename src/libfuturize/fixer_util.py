"""
Utility functions from 2to3, 3to2 and python-modernize (and some home-grown
ones).

Licences:
2to3: PSF License v2
3to2: Apache Software License (from 3to2/setup.py)
python-modernize licence: BSD (from python-modernize/LICENSE)
"""

from lib2to3.fixer_util import (FromImport, Newline, is_import,
                                find_root, does_tree_import, Comma)
from lib2to3.pytree import Leaf, Node
from lib2to3.pygram import python_symbols as syms, python_grammar
from lib2to3.pygram import token
from lib2to3.fixer_util import (Node, Call, Name, syms, Comma, Number)
import re


## These functions are from 3to2 by Joe Amenta:

def Star(prefix=None):
    return Leaf(token.STAR, u'*', prefix=prefix)

def DoubleStar(prefix=None):
    return Leaf(token.DOUBLESTAR, u'**', prefix=prefix)

def Minus(prefix=None):
    return Leaf(token.MINUS, u'-', prefix=prefix)

def commatize(leafs):
    u"""
    Accepts/turns: (Name, Name, ..., Name, Name) 
    Returns/into: (Name, Comma, Name, Comma, ..., Name, Comma, Name)
    """
    new_leafs = []
    for leaf in leafs:
        new_leafs.append(leaf)
        new_leafs.append(Comma())
    del new_leafs[-1]
    return new_leafs

def indentation(node):
    u"""
    Returns the indentation for this node
    Iff a node is in a suite, then it has indentation.
    """
    while node.parent is not None and node.parent.type != syms.suite:
        node = node.parent
    if node.parent is None:
        return u""
    # The first three children of a suite are NEWLINE, INDENT, (some other node)
    # INDENT.value contains the indentation for this suite
    # anything after (some other node) has the indentation as its prefix.
    if node.type == token.INDENT:
        return node.value
    elif node.prev_sibling is not None and node.prev_sibling.type == token.INDENT:
        return node.prev_sibling.value
    elif node.prev_sibling is None:
        return u""
    else:
        return node.prefix

def indentation_step(node):
    u"""
    Dirty little trick to get the difference between each indentation level
    Implemented by finding the shortest indentation string
    (technically, the "least" of all of the indentation strings, but
    tabs and spaces mixed won't get this far, so those are synonymous.)
    """
    r = find_root(node)
    # Collect all indentations into one set.
    all_indents = set(i.value for i in r.pre_order() if i.type == token.INDENT)
    if not all_indents:
        # nothing is indented anywhere, so we get to pick what we want
        return u"    " # four spaces is a popular convention
    else:
        return min(all_indents)

def suitify(parent):
    u"""
    Turn the stuff after the first colon in parent's children
    into a suite, if it wasn't already
    """
    for node in parent.children:
        if node.type == syms.suite:
            # already in the prefered format, do nothing
            return

    # One-liners have no suite node, we have to fake one up
    for i, node in enumerate(parent.children):
        if node.type == token.COLON:
            break
    else:
        raise ValueError(u"No class suite and no ':'!")
    # Move everything into a suite node
    suite = Node(syms.suite, [Newline(), Leaf(token.INDENT, indentation(node) + indentation_step(node))])
    one_node = parent.children[i+1]
    one_node.remove()
    one_node.prefix = u''
    suite.append_child(one_node)
    parent.append_child(suite)

def NameImport(package, as_name=None, prefix=None):
    u"""
    Accepts a package (Name node), name to import it as (string), and
    optional prefix and returns a node:
    import <package> [as <as_name>]
    """
    if prefix is None:
        prefix = u""
    children = [Name(u"import", prefix=prefix), package]
    if as_name is not None:
        children.extend([Name(u"as", prefix=u" "),
                         Name(as_name, prefix=u" ")])
    return Node(syms.import_name, children)

_compound_stmts = (syms.if_stmt, syms.while_stmt, syms.for_stmt, syms.try_stmt, syms.with_stmt)
_import_stmts = (syms.import_name, syms.import_from)

def import_binding_scope(node):
    u"""
    Generator yields all nodes for which a node (an import_stmt) has scope
    The purpose of this is for a call to _find() on each of them
    """
    # import_name / import_from are small_stmts
    assert node.type in _import_stmts
    test = node.next_sibling
    # A small_stmt can only be followed by a SEMI or a NEWLINE.
    while test.type == token.SEMI:
        nxt = test.next_sibling
        # A SEMI can only be followed by a small_stmt or a NEWLINE
        if nxt.type == token.NEWLINE:
            break
        else:
            yield nxt
        # A small_stmt can only be followed by either a SEMI or a NEWLINE
        test = nxt.next_sibling
    # Covered all subsequent small_stmts after the import_stmt
    # Now to cover all subsequent stmts after the parent simple_stmt
    parent = node.parent
    assert parent.type == syms.simple_stmt
    test = parent.next_sibling
    while test is not None:
        # Yes, this will yield NEWLINE and DEDENT.  Deal with it.
        yield test
        test = test.next_sibling

    context = parent.parent
    # Recursively yield nodes following imports inside of a if/while/for/try/with statement
    if context.type in _compound_stmts:
        # import is in a one-liner
        c = context
        while c.next_sibling is not None:
            yield c.next_sibling
            c = c.next_sibling
        context = context.parent

    # Can't chain one-liners on one line, so that takes care of that.

    p = context.parent
    if p is None:
        return

    # in a multi-line suite

    while p.type in _compound_stmts:

        if context.type == syms.suite:
            yield context

        context = context.next_sibling

        if context is None:
            context = p.parent
            p = context.parent
            if p is None:
                break

def ImportAsName(name, as_name, prefix=None):
    new_name = Name(name)
    new_as = Name(u"as", prefix=u" ")
    new_as_name = Name(as_name, prefix=u" ")
    new_node = Node(syms.import_as_name, [new_name, new_as, new_as_name])
    if prefix is not None:
        new_node.prefix = prefix
    return new_node


def future_import(feature, node):
    """
    This seems to work
    """
    root = find_root(node)

    if does_tree_import(u"__future__", feature, node):
        return

    # Look for a shebang line
    shebang_idx = None

    for idx, node in enumerate(root.children):
        # If it's a shebang line, attach the prefix to
        if is_shebang_comment(node):
            shebang_idx = idx
        if node.type == syms.simple_stmt and \
           len(node.children) > 0 and node.children[0].type == token.STRING:
            # skip over docstring
            continue
        names = check_future_import(node)
        if not names:
            # not a future statement; need to insert before this
            break
        if feature in names:
            # already imported
            return

    import_ = FromImport(u'__future__', [Leaf(token.NAME, feature, prefix=" ")])
    if shebang_idx == 0 and idx == 0:
        # If this __future__ import would go on the first line,
        # detach the shebang prefix from the current first line
        # and attach it to our new __future__ import node.
        import_.prefix = root.children[0].prefix
        root.children[0].prefix = u''
    children = [import_, Newline()]
    root.insert_child(idx, Node(syms.simple_stmt, children))


def future_import2(feature, node):
    """
    An alternative to future_import() which might not work ...
    """
    root = find_root(node)
    
    if does_tree_import(u"__future__", feature, node):
        return

    insert_pos = 0
    for idx, node in enumerate(root.children):
        if node.type == syms.simple_stmt and node.children and \
           node.children[0].type == token.STRING:
            insert_pos = idx + 1
            break

    for thing_after in root.children[insert_pos:]:
        if thing_after.type == token.NEWLINE:
            insert_pos += 1
            continue

        prefix = thing_after.prefix
        thing_after.prefix = u""
        break
    else:
        prefix = u""

    import_ = FromImport(u"__future__", [Leaf(token.NAME, feature, prefix=u" ")])

    children = [import_, Newline()]
    root.insert_child(insert_pos, Node(syms.simple_stmt, children, prefix=prefix))

def parse_args(arglist, scheme):
    u"""
    Parse a list of arguments into a dict
    """
    arglist = [i for i in arglist if i.type != token.COMMA]
    
    ret_mapping = dict([(k, None) for k in scheme])

    for i, arg in enumerate(arglist):
        if arg.type == syms.argument and arg.children[1].type == token.EQUAL:
            # argument < NAME '=' any >
            slot = arg.children[0].value
            ret_mapping[slot] = arg.children[2]
        else:
            slot = scheme[i]
            ret_mapping[slot] = arg

    return ret_mapping


# def is_import_from(node):
#     """Returns true if the node is a statement "from ... import ..."
#     """
#     return node.type == syms.import_from


def is_import_stmt(node):
    return (node.type == syms.simple_stmt and node.children and
            is_import(node.children[0]))


def touch_import_top(package, name_to_import, node):
    """Works like `does_tree_import` but adds an import statement at the
    top if it was not imported (but below any __future__ imports).

    Based on lib2to3.fixer_util.touch_import()

    Calling this multiple times adds the imports in reverse order.
        
    Also adds "standard_library.install_aliases()" after "from future import
    standard_library".  This should probably be factored into another function.
    """

    root = find_root(node)

    if does_tree_import(package, name_to_import, root):
        return

    # Ideally, we would look for whether futurize --all-imports has been run,
    # as indicated by the presence of ``from builtins import (ascii, ...,
    # zip)`` -- and, if it has, we wouldn't import the name again.

    # Look for __future__ imports and insert below them
    found = False
    for name in ['absolute_import', 'division', 'print_function',
                 'unicode_literals']:
        if does_tree_import('__future__', name, root):
            found = True
            break
    if found:
        # At least one __future__ import. We want to loop until we've seen them
        # all.
        start, end = None, None
        for idx, node in enumerate(root.children):
            if check_future_import(node):
                start = idx
                # Start looping
                idx2 = start
                while node:
                    node = node.next_sibling
                    idx2 += 1
                    if not check_future_import(node):
                        end = idx2
                        break
                break
        assert start is not None
        assert end is not None
        insert_pos = end
    else:
        # No __future__ imports.
        # We look for a docstring and insert the new node below that. If no docstring
        # exists, just insert the node at the top.
        for idx, node in enumerate(root.children):
            if node.type != syms.simple_stmt:
                break
            if not (node.children and node.children[0].type == token.STRING):
                # This is the usual case.
                break
        insert_pos = idx

    if package is None:
        import_ = Node(syms.import_name, [
            Leaf(token.NAME, u"import"),
            Leaf(token.NAME, name_to_import, prefix=u" ")
        ])
    else:
        import_ = FromImport(package, [Leaf(token.NAME, name_to_import, prefix=u" ")])
        if name_to_import == u'standard_library':
            # Add:
            #     standard_library.install_aliases()
            # after:
            #     from future import standard_library
            install_hooks = Node(syms.simple_stmt,
                                 [Node(syms.power,
                                       [Leaf(token.NAME, u'standard_library'),
                                        Node(syms.trailer, [Leaf(token.DOT, u'.'),
                                        Leaf(token.NAME, u'install_aliases')]),
                                        Node(syms.trailer, [Leaf(token.LPAR, u'('),
                                                            Leaf(token.RPAR, u')')])
                                       ])
                                 ]
                                )
            children_hooks = [install_hooks, Newline()]
        else:
            children_hooks = []
        
        FromImport(package, [Leaf(token.NAME, name_to_import, prefix=u" ")])

    children_import = [import_, Newline()]
    root.insert_child(insert_pos, Node(syms.simple_stmt, children_import))
    if len(children_hooks) > 0:
        root.insert_child(insert_pos + 1, Node(syms.simple_stmt, children_hooks))


## The following functions are from python-modernize by Armin Ronacher:
# (a little edited).

def check_future_import(node):
    """If this is a future import, return set of symbols that are imported,
    else return None."""
    # node should be the import statement here
    savenode = node
    if not (node.type == syms.simple_stmt and node.children):
        return set()
    node = node.children[0]
    # now node is the import_from node
    if not (node.type == syms.import_from and
            # node.type == token.NAME and      # seems to break it
            hasattr(node.children[1], 'value') and
            node.children[1].value == u'__future__'):
        return set()
    node = node.children[3]
    # now node is the import_as_name[s]
    # print(python_grammar.number2symbol[node.type])  # breaks sometimes
    if node.type == syms.import_as_names:
        result = set()
        for n in node.children:
            if n.type == token.NAME:
                result.add(n.value)
            elif n.type == syms.import_as_name:
                n = n.children[0]
                assert n.type == token.NAME
                result.add(n.value)
        return result
    elif node.type == syms.import_as_name:
        node = node.children[0]
        assert node.type == token.NAME
        return set([node.value])
    elif node.type == token.NAME:
        return set([node.value])
    else:
        # TODO: handle brackets like this:
        #     from __future__ import (absolute_import, division)
        assert False, "strange import: %s" % savenode


SHEBANG_REGEX = r'^#!\s*.*python'

def is_shebang_comment(node):
    """
    Comments are prefixes for Leaf nodes. Returns whether the given node has a
    prefix that looks like a shebang line.
    """
    return bool(re.match(SHEBANG_REGEX, node.prefix))


def wrap_in_fn_call(fn_name, args, prefix=None):
    """
    Example:
    >>> wrap_in_fn_call("oldstr", (arg,))
    oldstr(arg)

    >>> wrap_in_fn_call("olddiv", (arg1, arg2))
    olddiv(arg1, arg2)
    """
    assert len(args) > 0
    if len(args) == 1:
        newargs = args
    elif len(args) == 2:
        expr1, expr2 = args
        newargs = [expr1, Comma(), expr2]
    else:
        assert NotImplementedError('write me')
    return Call(Name(fn_name), newargs, prefix=prefix)

