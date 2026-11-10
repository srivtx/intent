"""Representation discovery: decide how each collection is stored, and say why.

The program is a service: any capability may be called any number of times, in any order.
So the planner minimises the per-call cost of every declared capability, and pays for an
auxiliary structure only when some declared capability needs it. Every decision records the
source lines that caused it.
"""
from dataclasses import dataclass, field

from .ir import STATE, conjuncts, lookups, looks_into, task_exprs, walk_cond_exprs, walk_expr


@dataclass
class CollPlan:
    name: str
    indexes: list = field(default_factory=list)       # property names with a hash index
    removal: str = None                               # None | 'swap' | 'shift'
    decisions: list = field(default_factory=list)     # (title, detail, [(line, why)])


@dataclass
class Plan:
    colls: dict = field(default_factory=dict)
    tasks: dict = field(default_factory=dict)         # task name -> (cost, how)
    picks: dict = field(default_factory=dict)         # task name -> (unique property, the value it must equal)
    local_rules: bool = False                         # every rule reads and changes one record only


def pick_of(prog, t):
    """If the task's condition fixes a unique property, at most one record can match: which one?

    "increase the points of the player with a given name": name is unique, so the one player
    is found through the index instead of looking at every player.
    """
    c = prog.collections.get(t.coll)
    if c is None or c.name == STATE or t.kind not in ('update', 'list', 'agg') or t.where is None:
        return None
    if any(e[0] == 'rand' for e in walk_cond_exprs(t.where)):
        return None                     # chance is drawn once per record looked at; keep looking at each
    for part in conjuncts(t.where):
        if part[0] != 'cmp' or part[1] != 'eq':
            continue
        for a, b in ((part[2], part[3]), (part[3], part[2])):
            if a[0] == 'field' and c.fields[a[1]].unique and \
                    all(e[0] in ('num', 'str', 'param', 'value', 'bin') for e in walk_expr(b)):
                return a[1], b
    return None


def one_record(t):
    """Does this rule read and change nothing but the record it is looking at?"""
    return t.kind == 'update' and not lookups(t) and \
        all(e[0] in ('num', 'str', 'field', 'bin', 'if') for e in task_exprs(t))


def c_each(prog, t):
    """Is the look into other records asked again for every record this task visits?"""
    return t.coll in prog.real() and t.kind not in ('make', 'add', 'calc')


def reaches(t, ref):
    """Does this task read a property of the record its rows belong to?"""
    return any(e[0] == 'pfield' and e[1] == ref for e in task_exprs(t)) or \
        any(n.startswith(ref + '.') for n in t.fields or [])


def narrow_settle(prog, plan, t):
    """After this command, how much do the standing rules have to look at again?

    'all'  - every rule, every record (always right)
    'row'  - only the one record the command added or changed
    'none' - nothing: records were only removed, and no rule reads another record
    The narrow answers are only given when every rule reads and changes a single record, so a
    record nobody touched is still exactly as the rules left it.
    """
    if not plan.local_rules or t.on or t not in prog.tasks:
        return 'all'
    if t.kind in ('remove_key', 'remove_where'):
        return 'none'
    if t.kind == 'add' or (t.kind == 'update' and t.name in plan.picks):
        return 'row' if any(r.coll == t.coll for r in prog.rules) else 'none'
    return 'all'


def make_plan(prog, no_index=False):
    plan = Plan()
    for c in prog.collections.values():
        cp = CollPlan(c.name)
        plan.colls[c.name] = cp
        tasks = [t for t in prog.work() if t.coll == c.name]
        adds = [t for t in tasks if t.kind in ('add', 'make')]
        if c.name == STATE:
            cp.decisions.append(('storage', f'kept side by side in one place, {8 * len(c.fields)} bytes', []))
        else:
            cp.decisions.append((
                'storage', f'one growable array of {c.name} records, {8 * len(c.fields)} bytes each', []))
        for f in c.unique_fields():
            why = []
            if adds:
                why.append((f.unique_line, f'{f.name} is unique, so every add must look for an existing {f.name}'))
            for t in tasks:
                if t.kind in ('find', 'remove_key') and t.key == f.name:
                    why.append((t.line, f'"{t.name}" picks one {c.name} by {f.name} on every call'))
                elif (pick_of(prog, t) or ('',))[0] == f.name:
                    why.append((t.line, f'"{t.name}" is about the one {c.name} with a certain {f.name}'))
            if prog.key_of(c.name) is f:
                for d, rf in prog.children_of(c.name):
                    for t in prog.work():
                        if t.coll != d.name:
                            continue
                        if t.kind == 'add':
                            why.append((rf.line, f'every new {d.name} must check that its {c.name} exists'))
                        elif reaches(t, rf.name):
                            why.append((t.line, f'"{t.name}" looks up the {c.name} of each {d.name}'))
            if not why:
                continue
            if no_index:
                cp.decisions.append((f'no index on {f.name}', 'disabled with --no-index; these now scan', why))
            else:
                cp.indexes.append(f.name)
                cp.decisions.append((f'index on {f.name}',
                                     'open-addressing hash table from the property to the row number', why))
        for t in tasks:
            if t.kind in ('find', 'remove_key') and not c.fields[t.key].unique:
                cp.decisions.append((f'no index on {t.key}', 'it is not unique, so a lookup may match many rows',
                                     [(t.line, f'"{t.name}" scans')]))
        single = [t for t in tasks if t.kind == 'remove_key' and c.fields[t.key].unique]
        if single:
            if c.ordered:
                cp.removal = 'shift'
                cp.decisions.append(('removal closes the gap', 'later rows move up one place, O(n)',
                                     [(c.ordered_line, 'insertion order is part of the meaning'),
                                      (single[0].line, f'"{single[0].name}" removes one {c.name}')]))
            else:
                cp.removal = 'swap'
                cp.decisions.append(('removal swaps in the last row', 'O(1), but changes the stored order',
                                     [(single[0].line, f'"{single[0].name}" removes one {c.name}'),
                                      (c.ordered_line or c.line, 'nothing says the order matters')]))
        for t in tasks:
            idx = t.key in cp.indexes if t.key else False
            pick = pick_of(prog, t)
            if pick and pick[0] in cp.indexes:
                plan.picks[t.name] = pick
                plan.tasks[t.name] = ('O(1) expected', f'one index probe on {pick[0]}, ' + {
                    'update': 'changed in place', 'list': 'then print', 'agg': 'nothing else looked at'}[t.kind])
            elif t.kind in ('add', 'make'):
                if cp.indexes:
                    plan.tasks[t.name] = ('O(1) expected', 'probe the index for a clash, then append')
                elif c.unique_fields():
                    plan.tasks[t.name] = ('O(n)', 'scan for a clash, then append')
                else:
                    plan.tasks[t.name] = ('O(1) amortised', 'append')
            elif t.kind == 'find':
                plan.tasks[t.name] = ('O(1) expected', 'one index probe') if idx else ('O(n)', 'scan every row')
            elif t.kind == 'remove_key':
                if not c.fields[t.key].unique:
                    plan.tasks[t.name] = ('O(n)', 'one pass keeping the rows that do not match')
                elif c.ordered:
                    plan.tasks[t.name] = ('O(n)', ('index probe' if idx else 'scan') + ', then close the gap')
                elif idx:
                    plan.tasks[t.name] = ('O(1) expected', 'index probe, swap the last row into the hole')
                else:
                    plan.tasks[t.name] = ('O(n)', 'scan, swap the last row into the hole')
            elif t.kind == 'remove_where':
                plan.tasks[t.name] = ('O(n)', 'one pass keeping the rows that stay' +
                                      (', then rebuild the index' if cp.indexes else ''))
            elif t.kind == 'update':
                plan.tasks[t.name] = ('O(n)', 'one pass, changed in place')
            elif t.kind == 'list':
                if t.order:
                    plan.tasks[t.name] = ('O(n log n)', 'collect matching row numbers, sort them, print' +
                                          (f' the first {t.limit}' if t.limit is not None else ''))
                elif t.limit is not None:
                    plan.tasks[t.name] = ('O(n)', f'one pass, printing only the first {t.limit} that match')
                else:
                    plan.tasks[t.name] = ('O(n)', 'one pass; filter and output fused, nothing copied')
            elif t.kind == 'agg':
                plan.tasks[t.name] = ('O(n)', 'one pass, constant extra memory')
    for c in prog.collections.values():
        for f in c.fields.values():
            if f.ref:
                k = prog.key_of(f.ref)
                plan.colls[c.name].decisions.append((
                    f'each {c.name} stores the {k.name if k else "key"} of its {f.ref}',
                    'a value, not a pointer, so rows on both sides can move freely', [(f.line, 'the relationship')]))
    for t in prog.work():
        c = prog.collections.get(t.coll)
        if c is None:
            continue
        cost, how = plan.tasks[t.name]
        if c.name == STATE:
            cost, how = 'O(1)', ('read the value' if t.kind == 'list' else 'change the value in place')
        if t.kind in ('add', 'make') and any(f.ref for f in c.fields.values()):
            how += ', after checking that what it belongs to exists'
        if t.kind in ('remove_key', 'remove_where'):
            for d, rf in prog.children_of(c.name):
                if rf.on_removed == 'cascade':
                    how += f'; then one pass over {d.label.lower()} to drop those left without a {c.name}'
                elif rf.on_removed == 'restrict':
                    how += f'; first a pass over {d.label.lower()} to see that none belong to it'
        plan.tasks[t.name] = (cost, how)
    for t in prog.tasks:
        if t.kind == 'calc':
            plan.tasks[t.name] = ('O(1)', 'straight-line arithmetic')
    for t in prog.work():
        seen = sorted(looks_into(t))
        if seen:                        # "if any shot ...", "the number of cells whose ...": asked by passing over them
            cost, how = plan.tasks[t.name]
            those = ' and '.join(prog.collections[n].label.lower() for n in seen)
            each = c_each(prog, t)
            plan.tasks[t.name] = (cost if not each else 'O(n x m)',
                                  how + f'; {"for each one, " if each else ""}a pass over the {those} to answer what it asks of them')
    plan.local_rules = bool(prog.rules) and all(one_record(r) for r in prog.rules)
    for t in prog.tasks + prog.events:
        if t.kind in ('add', 'remove_key', 'remove_where', 'update', 'make') and prog.rules:
            cost, how = plan.tasks[t.name]
            n = len(prog.rules)
            narrow = narrow_settle(prog, plan, t)
            if narrow == 'none':
                how += '; no rule has to look again, since each rule reads only the record it changes'
            elif narrow == 'row':
                how += f'; then the rules look again at just that {t.coll}'
            else:
                how += f'; then the {n} rule{"s are" if n > 1 else " is"} applied until nothing changes'
            plan.tasks[t.name] = (cost, how)
    return plan
