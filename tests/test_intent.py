"""Tests for the four claims the prototype makes.

  1. Many phrasings, one meaning           (TestPhrasings)
  2. Never guess: ask, pointing at the words (TestQuestions)
  3. Representation follows declared behaviour (TestPlanner)
  4. Native code means what the reference interpreter says (TestNativeAgainstReference)
and for the flexibility added after the first version:
  5. Slips of spelling are corrected only when one correction fits (TestSpelling)
  6. Programs can teach the compiler words                         (TestDefinitions)
  7. Word order, rankings, ranges, percentages                     (TestFlexibility)
  8. The example apps, and remembering between runs                (TestApps)
  9. Bugs found by the gemini-build stress experiments stay fixed  (TestStressFindings)
 10. Relationships between collections                             (TestRelationships)
 11. Calculations, single values and standing rules                (TestThinking)
 12. Time, keys, a board, and playing in a terminal                (TestLive)
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from intentc.check import check                 # noqa: E402
from intentc.cli import build                   # noqa: E402
from intentc.interp import Machine              # noqa: E402
from intentc.ir import canon                    # noqa: E402
from intentc.parser import parse                # noqa: E402
from intentc.plan import make_plan              # noqa: E402

BASE = ('Customers is a collection.\n'
        'Each customer has a name, an age (number), a salary (number) and an email.\n')


def understand(text, base=BASE):
    prog, diags, p = parse(base + text)
    diags += check(prog, p.src)
    return prog, [d for d in diags if d.level != 'note'], p


def meaning(text, base=BASE):
    prog, diags, _ = understand(text, base)
    assert not diags, f'{text!r}: {[d.msg for d in diags]}'
    assert len(prog.tasks) == 1, text
    return canon(prog.tasks[0])


def problem(text, base=BASE):
    prog, diags, p = understand(text, base)
    assert len(diags) == 1, f'{text!r}: {[d.msg for d in diags]}'
    d = diags[0]
    return d.level, p.src.line_text(d.line)[d.start:d.end], d


class TestPhrasings(unittest.TestCase):
    def same(self, expected, phrasings):
        for ph in phrasings:
            with self.subTest(ph):
                self.assertEqual(meaning(ph), expected)

    def test_double_age(self):
        self.same('update customer: age = age * 2', [
            # the four from the research conversation
            'Transform the age of each customer by multiplying it by 2.',
            'For every customer, double their age.',
            "Take the customer collection and make everyone's age twice as large.",
            "Customers: increase each person's age to two times its current value.",
            # and more
            'in each customer multiply the age by 2',
            "Each customer's age should be multiplied by 2",
            'TRANSFORM Customers:\n  Age becomes Age multiplied by 2',
            'So basically, I want to double the age of all the customers please',
            'Double every customer\'s age.',
            'age = age * 2',
            'Set the age to twice the age.',
            'Update customers: age becomes 2 times age',
            'Multiply the ages by two.',
            'Change the age by doubling it',
            'The age of every customer gets doubled.',
        ])

    def test_arithmetic_updates(self):
        self.same('update customer: salary = salary + 100', [
            'Increase the salary by 100.',
            'Add 100 to every salary.',
            'Raise each customer\'s salary by a hundred',
            'salary becomes salary plus 100',
            'Every salary should be increased by 100.',
        ])
        self.same('update customer: age = age - 1', [
            'Subtract 1 from the age.', 'Decrease age by one.', 'Reduce everyone\'s age by 1',
        ])

    def test_conditional_update(self):
        self.same('update customer: salary = salary * 2 where age > 60', [
            'Double the salary of customers whose age is over 60.',
            'If age is more than 60, double the salary.',
            'For every customer with age above 60, multiply the salary by 2',
        ])

    def test_filter(self):
        self.same('list name of customer where age >= 18', [
            'Show the names of customers whose age is at least 18.',
            'List the name of every customer with age no less than 18',
            'Give me the names of the customers where age >= 18.',
            'the names of customers whose age is not under 18',
        ])

    def test_aggregates(self):
        self.same('avg(age) of customer', ['What is the average age?', 'Show the mean age of the customers.',
                                           'average age'])
        self.same('sum(salary) of customer', ['Add up the salaries.', 'the total salary', 'Add all the salaries',
                                              'Give me the sum of the salaries of all customers.'])
        self.same('count() of customer where age < 18', ['How many customers have an age under 18?',
                                                         'Count the customers whose age is below 18.',
                                                         'the number of customers with age less than 18'])
        self.same('max(age) of customer', ['the largest age', 'What is the highest age?', 'maximum age'])

    def test_keyed(self):
        self.same('find customer by email', ['Find a customer by email.', 'Look up customers using their email',
                                             'Find the customer whose email is given.',
                                             'Find the customer with a given email.'])
        self.same('remove customer by email', ['Remove a customer by email.', 'Delete the customer with a given email'])

    def test_keep_is_remove_of_the_rest(self):
        self.assertEqual(meaning('Keep only the customers whose age is at least 18.'),
                         meaning('Remove the customers whose age is under 18.'))

    def test_sort(self):
        self.same('list all of customer sorted by age descending', [
            'Show the customers sorted by age, largest first.',
            'Sort the customers by age in descending order.',
            'List customers ordered by age descending',
        ])

    def test_calc(self):
        for ph in ['double: take a number n and return n multiplied by 2.',
                   'It will take a value of n and it will return a value of n multiplied by 2',
                   'Create a function that accepts a number n and returns that number times two.',
                   'take n and double it']:
            with self.subTest(ph):
                self.assertEqual(meaning(ph, base=''), 'calc(n) = <n> * 2')

    def test_block_syntax(self):
        prog, diags, _ = understand('', base='''COLLECTION Customers
Each customer has:
  Name: Text
  Age: Integer
  Email: Text

Requirements:
  Add a customer.
  Find a customer by email.
  Retrieve all customers.
  Email must be unique.
  Reject duplicates.
''')
        self.assertEqual(diags, [])
        self.assertEqual([canon(t) for t in prog.tasks],
                         ['add customer', 'find customer by email', 'list all of customer'])
        self.assertTrue(prog.collections['customer'].fields['email'].unique)


class TestQuestions(unittest.TestCase):
    def test_unknown_word_is_never_dropped(self):
        level, at, _ = problem('Show the largest positive age.')
        self.assertEqual((level, at), ('error', 'positive'))

    def test_filler_is_dropped(self):
        self.assertEqual(meaning('So basically, what I really want is to show the largest age please'),
                         'max(age) of customer')

    def test_pronoun_without_antecedent(self):
        level, at, d = problem('Transform customers and double it.')
        self.assertEqual((level, at), ('question', 'it'))
        self.assertIn('age', d.label)
        self.assertNotIn('email', d.label)       # text properties cannot be doubled
        level, at, _ = problem('each customer, it should be multiplied by 2')
        self.assertEqual((level, at), ('question', 'it'))

    def test_pronoun_with_two_antecedents(self):
        level, at, d = problem('Set age to salary and then double it.')
        self.assertEqual((level, at), ('question', 'it'))
        self.assertEqual(d.label, 'could be: age, salary')

    def test_sort_needs_a_property(self):
        level, _, d = problem('Sort the customers.')
        self.assertEqual(level, 'question')
        self.assertIn('by which property', d.msg)

    def test_remove_needs_a_selector(self):
        self.assertEqual(problem('Remove a customer.')[0], 'question')

    def test_by_is_two_ways(self):
        level, at, _ = problem('Show customers by age.')
        self.assertEqual((level, at), ('question', 'by age'))

    def test_comparison_needs_a_property(self):
        level, at, _ = problem('Count the customers over 25.')
        self.assertEqual((level, at), ('question', 'over 25'))

    def test_mixed_and_or(self):
        self.assertEqual(problem('Show customers whose age is over 5 and salary is 3 or age is under 2.')[0],
                         'question')

    def test_value_or_action(self):
        self.assertEqual(problem('age multiplied by 2')[0], 'question')

    def test_duplicate_policy_must_be_stated(self):
        level, _, d = problem('Emails are unique.\nAdd a customer.')
        self.assertEqual(level, 'question')
        self.assertIn('existing email', d.msg)
        self.assertEqual(understand('Emails are unique.\nReject duplicates.\nAdd a customer.')[1], [])

    def test_untyped_property(self):
        prog, diags, _ = understand('', base='Things is a collection.\nEach thing has a code and a weight.\n'
                                              'Show the total weight.\n')
        self.assertEqual(prog.collections['thing'].fields['weight'].how, 'inferred')
        self.assertEqual([(d.level, 'code' in d.msg) for d in diags], [('question', True)])

    def test_type_clash(self):
        base = 'Customers is a collection.\nEach customer has a name (text) and an age.\n'
        self.assertEqual(problem('Double the name.', base)[0], 'error')
        self.assertEqual(problem('Show customers whose name is over 5.', base)[0], 'error')

    def test_division_by_possible_zero(self):
        self.assertEqual(problem('Divide the salary by the age.')[0], 'question')

    def test_unknown_property(self):
        level, at, _ = problem('Double the height.')
        self.assertEqual((level, at), ('error', 'height'))


class TestPlanner(unittest.TestCase):
    def plan(self, text, **kw):
        prog, diags, _ = understand(text)
        self.assertEqual(diags, [])
        return make_plan(prog, **kw).colls['customer']

    def test_plain_array_when_nothing_is_keyed(self):
        cp = self.plan('Add a customer.\nShow all customers.\nDouble the age.')
        self.assertEqual((cp.indexes, cp.removal), ([], None))

    def test_unique_without_add_needs_no_index(self):
        self.assertEqual(self.plan('Emails are unique.\nShow all customers.').indexes, [])

    def test_index_for_keyed_lookup(self):
        cp = self.plan('Emails are unique.\nReject duplicates.\nAdd a customer.\nFind a customer by email.')
        self.assertEqual((cp.indexes, cp.removal), (['email'], None))

    def test_no_index_on_non_unique_key(self):
        self.assertEqual(self.plan('Add a customer.\nFind customers by name.').indexes, [])

    def test_removal_strategy_follows_order(self):
        common = 'Emails are unique.\nReject duplicates.\nAdd a customer.\nRemove a customer by email.\n'
        self.assertEqual(self.plan(common).removal, 'swap')
        self.assertEqual(self.plan(common + 'Keep customers in the order they were added.').removal, 'shift')

    def test_decisions_cite_source_lines(self):
        cp = self.plan('Emails are unique.\nReject duplicates.\nAdd a customer.\nFind a customer by email.')
        title, _, why = next(d for d in cp.decisions if d[0] == 'index on email')
        self.assertEqual([line for line, _ in why], [3, 6])


PROGRAMS = {
    'unordered_reject_text_key': '''
Customers is a collection. Each customer has a name, an age, a salary (number) and an email.
Emails are unique. Reject duplicates.
Add a customer. Find a customer by email. Remove a customer by email. Retrieve all customers.
For every customer, double their age.
raise: increase the salary by a given amount for customers whose age is at least a given age.
adults: the names of customers whose age is at least 18.
How many customers are there?
What is the average age?
Add up the salaries.
the largest salary
the smallest age of customers whose name is "ann"
by-age: show the customers sorted by age, largest first.
by-name: show the name and email of customers sorted by name.
Keep only the customers whose age is under a given limit.
Remove the customers whose name is a given name.
rename: set the name to "x" for customers whose salary is over 90.
halve: halve the salary.
neg: salary becomes salary divided by -1.
mix: show customers whose age is under 10 or salary is over 80 or name is "bob".
double: take a number n and return n times 2.
''',
    'ordered_replace_int_key': '''
Items is a collection. Each item has an id (number), a label (text) and a price (number).
No two items share an id. Replace duplicates.
Keep items in the order they were added.
Add an item. Find an item by id. Remove an item by id. List all items.
Triple the price of items whose price is less than a given price.
cheap: show the labels of items whose price is at most 20.
count the items
total price
by-price: show items sorted by price.
by-label: sort the items by label in descending order.
Remove the items whose price is over a given price and label is not "keep".
average price of items whose id is above 10
''',
    'no_unique_fields': '''
People is a collection. Each person has a name, a city (text) and a score (number).
Add a person. Find people by city. Remove people by city. Show all people.
Increase the score by 5 where city is "rome".
largest score
by-score: show people sorted by score, lowest first.
''',
}


def commands(prog, rng, n):
    names = ['ann', 'bob', 'cy', 'dee', 'x', 'keep', 'rome', 'oslo', 'lima']
    small = {f.name for c in prog.collections.values() for f in c.fields.values() if f.unique or f.ref}
    out = []
    for _ in range(n):
        t = rng.choice(prog.tasks)
        if t.kind == 'add' and rng.random() < 0.5:
            t = rng.choice([x for x in prog.tasks if x.kind == 'add'])
        args = []
        for p in t.params:
            if t.ptypes[p] == 'int' and p in small and rng.random() < 0.85:
                args.append(str(rng.randint(0, 12)))        # keys and links: make hits likely
            elif t.ptypes[p] == 'int':
                args.append(str(rng.choice([rng.randint(-20, 120), rng.randint(0, 30),
                                            2 ** 62, -(2 ** 63), 0])))
            elif p == 'email':
                args.append(f'u{rng.randint(0, 25)}@x.io')
            else:
                args.append(rng.choice(names))
        if rng.random() < 0.02:
            args = args[:-1] if args else ['junk']
        if rng.random() < 0.02 and args:
            args[0] = 'not-a-number'
        out.append(t.name + (' ' + ','.join(args) if args else ''))
    out.append('no-such-command 1')
    return out


@unittest.skipUnless(shutil.which('clang'), 'clang is needed to build native code')
class TestNativeAgainstReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='intent-test-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def differential(self, name, text, no_index=False, seeds=6, n=400):
        src = os.path.join(self.dir, name + '.intent')
        exe = os.path.join(self.dir, name + ('-noindex' if no_index else ''))
        with open(src, 'w') as fh:
            fh.write(text)
        prog = build(src, exe, no_index=no_index, quiet=True)
        self.assertIsNotNone(prog, 'did not compile')
        tasks = {t.name: t for t in prog.tasks}
        for seed in range(seeds):
            rng = random.Random(seed)
            cmds = commands(prog, rng, n)
            # tag every command's output so the two transcripts can be compared command by command
            m = Machine(prog)
            expected = [m.run(c) for c in cmds]
            got = subprocess.run([exe], input='\n'.join(cmds) + '\n', capture_output=True, text=True, timeout=60)
            self.assertEqual(got.returncode, 0, got.stderr)
            lines = got.stdout.split('\n')[:-1]
            pos = 0
            for c, exp in zip(cmds, expected):
                act = lines[pos:pos + len(exp)]
                pos += len(exp)
                t = tasks.get(c.split(' ')[0])
                ordered = t is None or t.coll is None or prog.collections[t.coll].ordered
                if not ordered and t.kind == 'list' and t.limit is not None:
                    exp, act = len(exp), len(act)           # ties are broken by storage order
                elif not ordered and t.kind in ('list', 'find'):
                    exp, act = sorted(exp), sorted(act)     # order is not part of the meaning
                self.assertEqual(act, exp, f'seed {seed}, command {c!r}')
            self.assertEqual(pos, len(lines), f'seed {seed}: native printed extra lines')

    def test_unordered_reject_text_key(self):
        self.differential('a', PROGRAMS['unordered_reject_text_key'])

    def test_same_program_without_index(self):
        self.differential('a', PROGRAMS['unordered_reject_text_key'], no_index=True)

    def test_ordered_replace_int_key(self):
        self.differential('b', PROGRAMS['ordered_replace_int_key'])

    def test_ordered_without_index(self):
        self.differential('b', PROGRAMS['ordered_replace_int_key'], no_index=True)

    def test_no_unique_fields(self):
        self.differential('c', PROGRAMS['no_unique_fields'])

    def test_index_survives_growth_and_churn(self):
        text = ('Customers is a collection. Each customer has a name and an email. Emails are unique. '
                'Reject duplicates. Add a customer. Find a customer by email. Remove a customer by email. '
                'How many customers are there?')
        src = os.path.join(self.dir, 'churn.intent')
        exe = os.path.join(self.dir, 'churn')
        with open(src, 'w') as fh:
            fh.write(text)
        prog = build(src, exe, quiet=True)
        rng = random.Random(1)
        cmds = []
        for i in range(30000):
            k = rng.randint(0, 4000)
            cmds.append(rng.choice([f'add n{i},e{k}', f'add n{i},e{k}', f'remove-by-email e{k}',
                                    f'find-by-email e{k}']))
        cmds.append('count')
        m = Machine(prog)
        expected = [o for c in cmds for o in m.run(c)]
        got = subprocess.run([exe], input='\n'.join(cmds) + '\n', capture_output=True, text=True, timeout=120)
        self.assertEqual(got.stdout.split('\n')[:-1], expected)

def notes(text, base=BASE):
    prog, diags, p = parse(base + text)
    return [d.msg for d in diags if d.level == 'note' and d.line > base.count('\n')]


class TestSpelling(unittest.TestCase):
    def test_one_slip(self):
        for typo, right in [('Doubel the age.', 'double'), ('Find a customer by emial.', 'email'),
                            ('What is the avrage age?', 'average'), ('Show the custmers.', 'customers')]:
            with self.subTest(typo):
                self.assertTrue(meaning(typo))
                self.assertEqual(len(notes(typo)), 1)
                self.assertIn(f'as "{right}"', notes(typo)[0])

    def test_same_meaning_as_the_correct_spelling(self):
        self.assertEqual(meaning('Shwo teh customres sroted by aeg.'), meaning('Show the customers sorted by age.'))
        self.assertEqual(meaning('Remove the customers whos age is under 18.'),
                         meaning('Remove the customers whose age is under 18.'))

    def test_every_correction_is_reported(self):
        self.assertEqual(len(notes('Shwo teh customres sroted by aeg.')), 5)

    def test_a_far_off_word_is_still_an_error(self):
        level, where, _ = problem('Show the largest positive age.')
        self.assertEqual((level, where), ('error', 'positive'))

    def test_two_possible_corrections_is_a_question(self):
        base = ('Items is a collection.\nEach item has a cost (number) and a coat (number).\n')
        level, where, d = problem('Show the items sorted by coxt.', base)
        self.assertEqual((level, where), ('question', 'coxt'))
        self.assertIn('coat', d.label)
        self.assertIn('cost', d.label)

    def test_new_names_in_declarations_are_not_corrected(self):
        prog, diags, _ = understand('', 'Custmers is a collection.\nEach custmer has a nme.\n')
        self.assertIn('custmer', prog.collections)
        self.assertIn('nme', prog.collections['custmer'].fields)


DEFS = BASE + ('"older than" means age over.\n'
               'An adult is a customer whose age is at least 18.\n'
               'A senior is an adult older than 64.\n'
               'A rich customer is a customer whose salary is over 9000.\n'
               '"oldest" means with the largest age.\n')


class TestDefinitions(unittest.TestCase):
    def test_phrase(self):
        self.assertEqual(meaning('Show the customers older than 30.', DEFS), 'list all of customer where age > 30')

    def test_noun(self):
        self.assertEqual(meaning('How many adults are there?', DEFS), 'count() of customer where age >= 18')
        self.assertEqual(meaning('Remove the adults.', DEFS), 'remove customer where age >= 18')

    def test_definitions_build_on_each_other(self):
        self.assertEqual(meaning('Show the names of seniors.', DEFS),
                         'list name of customer where age >= 18 and age > 64')

    def test_noun_plus_more_conditions(self):
        self.assertEqual(meaning('Double the salary of adults whose salary is under 100.', DEFS),
                         'update customer: salary = salary * 2 where age >= 18 and salary < 100')

    def test_adjective(self):
        self.assertEqual(meaning('Show the rich customers sorted by name.', DEFS),
                         'list all of customer where salary > 9000 sorted by name ascending')

    def test_superlative(self):
        self.assertEqual(meaning('Show the oldest customer.', DEFS),
                         'list all of customer sorted by age descending, first 1')
        self.assertEqual(meaning('Show the 3 oldest adults.', DEFS),
                         'list all of customer where age >= 18 sorted by age descending, first 3')

    def test_label_or_scope(self):
        prog, diags, _ = understand('seniors: show the names of the seniors.\nAdults: double the salary.\n', DEFS)
        self.assertEqual(diags, [])
        self.assertEqual(prog.tasks[0].name, 'seniors')
        self.assertEqual(canon(prog.tasks[1]), 'update customer: salary = salary * 2 where age >= 18')

    def test_a_word_means_one_thing(self):
        level, where, _ = problem('"over" means under.')
        self.assertEqual((level, where), ('error', '"over"'))

    def test_meaning_must_be_understood(self):
        level, where, _ = problem('"posh" means fancy.')
        self.assertEqual((level, where), ('error', 'fancy'))

    def test_taught_words_are_spell_checked_too(self):
        self.assertEqual(meaning('Show the adluts.', DEFS), 'list all of customer where age >= 18')


class TestFlexibility(unittest.TestCase):
    def same(self, expected, phrasings, base=BASE):
        for ph in phrasings:
            with self.subTest(ph):
                self.assertEqual(meaning(ph, base), expected)

    def test_word_order(self):
        self.same('update customer: age = age * 2', [
            'Double the age of every customer.', 'The age of every customer, double it.',
            'For each customer, the age becomes twice the age.'])
        self.same('remove customer where age < 18', [
            'Remove the customers whose age is under 18.', 'Customers whose age is under 18: remove them.',
            'If the age is under 18, delete the customer.', 'Wipe out every customer with an age below 18.'])
        self.same('find customer by email', ['Find a customer by email.', 'By email, find a customer.',
                                             'Look up a customer using their email.'])
        self.same('list all of customer sorted by age descending', [
            'Show the customers sorted by age, largest first.', 'Sorted by age, largest first, show the customers.',
            'The customers, sorted by age, show them largest first.'])

    def test_ranking(self):
        self.same('list all of customer sorted by salary descending, first 3', [
            'Show the top 3 customers by salary.', 'Show the 3 customers with the highest salary.',
            'the top three customers by salary'])
        self.assertEqual(meaning('Show the name of the customer with the lowest age.'),
                         'list name of customer sorted by age ascending, first 1')

    def test_first_needs_an_order(self):
        level, where, _ = problem('Show the first 5 customers.')
        self.assertEqual((level, where), ('question', 'the first 5'))
        self.assertEqual(meaning('Show the first 5 customers.', BASE + 'Keep customers in the order they were added.\n'),
                         'list all of customer, first 5')

    def test_range(self):
        self.same('list all of customer where age >= 18 and age <= 30', [
            'Show customers whose age is between 18 and 30.', 'Show customers with an age between 18 and 30.',
            'Show customers whose age is at least 18 and at most 30.'])

    def test_percent(self):
        self.same('update customer: salary = salary + ((salary * 10) / 100)', [
            'Increase every salary by 10 percent.', 'Raise the salary by 10%.'])

    def test_remove_everything_only_when_said(self):
        self.same('remove customer', ['Remove all customers.', 'Delete everyone.'])
        self.assertEqual(problem('Remove a customer.')[0], 'question')

    def test_question_is_not_a_declaration(self):
        self.assertEqual(meaning('Which customers have a salary over 5000?'), 'list all of customer where salary > 5000')


@unittest.skipUnless(shutil.which('clang'), 'clang is needed to build native code')
class TestApps(TestNativeAgainstReference):
    def app(self, name):
        with open(os.path.join(ROOT, 'examples', name + '.intent')) as fh:
            self.differential(name, fh.read(), seeds=4, n=300)

    def test_leaderboard(self):
        self.app('leaderboard')

    def test_todo(self):
        self.app('todo')

    def test_shop(self):
        self.app('shop')

    def test_tour_of_the_language(self):
        self.app('tour')

    def test_help_lists_capabilities(self):
        src, exe = os.path.join(self.dir, 'h.intent'), os.path.join(self.dir, 'h')
        with open(src, 'w') as fh:
            fh.write('Pets is a collection. Each pet has a name. Add a pet. Show the pets.')
        prog = build(src, exe, quiet=True)
        got = subprocess.run([exe], input='help\n', capture_output=True, text=True)
        self.assertEqual(got.stdout, 'add <name>\nlist\n')
        self.assertEqual(Machine(prog).run('help'), ['add <name>', 'list'])

    def test_remembers_between_runs(self):
        src, exe = os.path.join(self.dir, 'r.intent'), os.path.join(self.dir, 'r')
        log = os.path.join(self.dir, 'r.log')
        with open(src, 'w') as fh:
            fh.write('Pets is a collection. Each pet has a name and an age (number). Names are unique. '
                     'Reject duplicates. Keep pets in the order they were added. Add a pet. '
                     'Remove a pet by name. Double the age. Show the pets.')
        build(src, exe, quiet=True)

        def run(text):
            return subprocess.run([exe, log], input=text, capture_output=True, text=True).stdout

        self.assertEqual(run('add rex,3\nadd tom,5\nlist\n'), 'rex,3\ntom,5\n')
        self.assertEqual(run('double-age\nremove-by-name rex\nadd ivy,1'), '')      # last line has no newline
        self.assertEqual(run('list\n'), 'tom,10\nivy,1\n')
        with open(log) as fh:                                       # queries are not recorded
            self.assertEqual(fh.read(), 'add rex,3\nadd tom,5\ndouble-age\nremove-by-name rex\nadd ivy,1\n')


class TestStressFindings(unittest.TestCase):
    """Each of these was a real bug found by building larger programs with the language."""

    def test_not_between_is_outside_the_range(self):
        self.assertEqual(meaning('Show customers whose age is not between 18 and 30.'),
                         'list all of customer where age < 18 or age > 30')
        self.assertEqual(problem('Show customers whose salary is over 5 and whose age is not between 1 and 3.')[0],
                         'question')

    def test_taught_word_inside_a_hyphenated_name(self):
        prog, diags, _ = understand('"vip" means salary at least 100.\nshow-vip: show the names of customers vip.\n')
        self.assertEqual(diags, [])
        self.assertEqual(prog.tasks[0].name, 'show-vip')

    def test_property_named_like_a_collection(self):
        base = ('Customers is a collection.\nEach customer has a handle (text).\n'
                'Bookings is a collection.\nEach booking has an id (number) and a customer (text).\n')
        self.assertEqual(meaning('Add a customer.', base), 'add customer')
        self.assertEqual(meaning('Show the bookings whose customer is "ann".', base),
                         'list all of booking where customer == "ann"')

    def test_declared_name_beats_builtin_phrase(self):
        base = 'Orders is a collection.\nEach order has an id (number) and a price (number).\n'
        self.assertEqual(meaning('Find an order by id.', base), 'find order by id')
        self.assertEqual(meaning('Show the orders sorted by price.', base),
                         'list all of order sorted by price ascending')

    def test_bare_trailing_condition(self):
        self.assertEqual(meaning('"cheap" means salary is 10.\nShow the customers cheap.\n'),
                         'list all of customer where salary == 10')

    def test_calculation_on_the_left(self):
        self.assertEqual(meaning('Show customers whose age times 2 is over salary.'),
                         'list all of customer where age * 2 > salary')

    def test_text_tests(self):
        self.assertEqual(meaning('Show customers whose name contains "ob".'),
                         'list all of customer where name contains "ob"')
        self.assertEqual(meaning('Show customers whose email does not end with ".io".'),
                         'list all of customer where email does not end with ".io"')
        prog, diags, _ = understand('', 'Samples is a collection.\nEach sample contains a message and a level.\n')
        self.assertEqual(list(prog.collections['sample'].fields), ['message', 'level'])

    def test_parity_and_modulo(self):
        self.assertEqual(meaning('Show customers whose age is even.'), 'list all of customer where age mod 2 == 0')
        self.assertEqual(meaning('Show customers whose age is not even.'), meaning('Show customers whose age is odd.'))
        self.assertEqual(meaning('Set the age to age mod 7.'), 'update customer: age = age mod 7')

    def test_own_definition_beats_builtin_word(self):
        self.assertEqual(meaning('An even customer is a customer whose age is 2.\nShow the even customers.\n'),
                         'list all of customer where age == 2')

    def test_rules_apply_to_the_collection_just_described(self):
        prog, diags, _ = understand('', 'Pets is a collection.\nEach pet has a tag.\nToys is a collection.\n'
                                    'Each toy has a code.\nCodes are unique.\nReject duplicates.\nAdd a toy.\n')
        self.assertEqual(prog.collections['toy'].on_dup, 'reject')
        self.assertIsNone(prog.collections['pet'].on_dup)


STORE = """Customers is a collection.
Each customer has a name and a city (text).
Names are unique. Reject duplicates.
Orders is a collection.
Each order has a number (number), a customer and a total (number).
Numbers are unique. %s
%s
Lines is a collection.
Each line has a sku (text) and a quantity (number).
Each line belongs to an order.
%s
signup: add a customer.
place: add an order.
add-line: add a line.
close: remove a customer by name.
cancel: remove an order by number.
purge: remove the customers whose city is a given city.
refund: remove the orders whose total is over a given limit.
orders-of: show the orders of a given customer.
spent: what is the sum of the total of orders for a given customer?
lines-of: show the sku and quantity of lines for a given order.
receipt: show the number, the total and the customer's city of orders sorted by number.
from-city: show the numbers of orders whose customer's city is a given city.
discount: decrease the total by 10 percent for orders whose customer's city is a given city.
who: show the order's customer of lines whose sku is a given sku.
contains-o: show the numbers of orders whose customer's name contains "o".
customers: show the customers.
orders: show the orders.
lines: show the lines.
"""
CASCADE = ('When a customer is removed, remove its orders.', 'When an order is removed, remove its lines.')
RESTRICT = ('A customer with orders cannot be removed.', 'An order with lines cannot be removed.')
STORE_BASE = STORE.split('signup:')[0]


class TestRelationships(TestNativeAgainstReference):
    def base(self, rules=CASCADE):
        return STORE_BASE % ('Reject duplicates.', '', '\n'.join(rules))

    def test_readings(self):
        b = self.base()
        for text, want in [
                ('Show the orders of a given customer.', 'list all of order where customer == <customer>'),
                ('For a given customer, show the orders.', 'list all of order where customer == <customer>'),
                ('How many orders does a given customer have?', 'count() of order where customer == <customer>'),
                ("Show the orders whose customer's city is \"rome\".", 'list all of order where customer.city == "rome"'),
                ('Show the orders where the city of the customer is "rome".',
                 'list all of order where customer.city == "rome"'),
                ("Show the number and the customer's city of orders.", 'list number, customer.city of order'),
                ("Show the lines whose order's customer is a given customer.",
                 'list all of line where order.customer == <customer>'),
                ('Remove the orders of a given customer.', 'remove order by customer')]:
            with self.subTest(text):
                self.assertEqual(meaning(text, b), want)

    def test_has_a_customer_is_the_same_declaration(self):
        prog, _, _ = understand('', 'Shops is a collection.\nEach shop has a name.\nItems is a collection.\n'
                                'Each item has an id and a shop.\n')
        self.assertEqual(prog.collections['item'].fields['shop'].ref, 'shop')

    def test_removal_rule_must_be_stated(self):
        level, _, d = problem('Remove a customer by name.', self.base(rules=()))
        self.assertEqual(level, 'question')
        self.assertIn('orders of a removed customer', d.msg)

    def test_rules(self):
        prog, diags, _ = understand('', self.base(RESTRICT))
        self.assertEqual(prog.collections['order'].fields['customer'].on_removed, 'restrict')
        prog, diags, _ = understand('', self.base())
        self.assertEqual(prog.collections['line'].fields['order'].on_removed, 'cascade')
        self.assertEqual(problem('Orders are removed with their customer.', self.base(rules=()))[0], 'question')

    def test_owner_must_be_identifiable(self):
        level, _, d = problem('Each item belongs to a shop.\n', 'Shops is a collection.\nEach shop has a name (text).\n'
                              'Items is a collection.\nEach item has an id (number).\n')
        self.assertEqual(level, 'question')
        self.assertIn('how is a shop identified', d.msg)

    def test_the_other_direction_is_refused_not_guessed(self):
        level, where, _ = problem('Show the customers who have orders.', self.base())
        self.assertEqual(level, 'error')

    def test_owner_key_gets_an_index_because_of_the_link(self):
        prog, diags, p = parse(STORE % ('Reject duplicates.', '', '\n'.join(CASCADE)))
        check(prog, p.src)
        plan = make_plan(prog)
        self.assertIn('name', plan.colls['customer'].indexes)
        self.assertTrue(any('must check that its customer exists' in why
                            for title, _, whys in plan.colls['customer'].decisions for _, why in whys))

    def test_native_cascade(self):
        self.differential('rel-cascade', STORE % ('Reject duplicates.', '', '\n'.join(CASCADE)), seeds=5, n=500)

    def test_native_cascade_ordered_replace_no_index(self):
        self.differential('rel-ordered', STORE % ('Replace duplicates.', 'Keep orders in the order they were added.',
                                                  '\n'.join(CASCADE)), no_index=True, seeds=4, n=400)

    def test_native_restrict(self):
        self.differential('rel-restrict', STORE % ('Reject duplicates.', '', '\n'.join(RESTRICT)), seeds=5, n=500)

    def test_store_example(self):
        with open(os.path.join(ROOT, 'examples', 'store.intent')) as fh:
            self.differential('store', fh.read(), seeds=4, n=400)


@unittest.skipUnless(shutil.which('clang'), 'clang is needed to build native code')
class TestService(unittest.TestCase):
    SRC = ('Users is a collection. Each user has an email (text) and an age (number). Emails are unique. '
           'Reject duplicates. Add a user. Find a user by email. Remove a user by email.')

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='intent-svc-')
        src = os.path.join(cls.dir, 's.intent')
        cls.exe = os.path.join(cls.dir, 's')
        with open(src, 'w') as fh:
            fh.write(cls.SRC)
        build(src, cls.exe, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_answers_each_request_over_a_pipe(self):
        p = subprocess.Popen([self.exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        try:
            for req, want in [('add a@x,3', None), ('find-by-email a@x', 'a@x,3'), ('find-by-email', 'error: missing email'),
                              ('find-by-email zz', 'none')]:
                p.stdin.write(req + '\n')
                p.stdin.flush()
                if want:
                    self.assertEqual(p.stdout.readline().rstrip('\n'), want)   # would hang if output were held back
        finally:
            p.stdin.close()
            p.wait(timeout=10)

    def test_only_real_changes_are_remembered(self):
        log = os.path.join(self.dir, 's.log')
        subprocess.run([self.exe, log], input='add a@x,3\nadd a@x,9\nadd b@x,notanumber\nadd\nremove-by-email zz\n'
                       'find-by-email a@x\nremove-by-email a@x\n', capture_output=True, text=True)
        with open(log) as fh:
            self.assertEqual(fh.read(), 'add a@x,3\nremove-by-email a@x\n')


MANY = """Contacts is a collection where each contact has a name, a city (text) and phones.
Names are unique. Reject duplicates.
Teams have a title (text), points and several tags (text).
Titles are unique. Replace duplicates.
Add a contact.
Add a phone to a given contact.
Show the phones of a given contact.
How many phones does a given contact have?
Remove a contact by name.
Remove the phones of a given contact.
Show the phones whose contact's city is a given city.
dial: show the phone and the contact's name of phones whose phone starts with a given prefix.
Add a team.
Add a tag to a given team.
Show the tags of a given team.
Remove the teams whose points is under a given limit.
Show the teams.
Show the contacts.
Show the phones.
Show the tags.
"""


class TestDescribing(TestNativeAgainstReference):
    """Declaring a collection in one breath, and properties that hold several values."""

    def fields(self, text, coll):
        prog, diags, _ = understand('', text)
        self.assertEqual(diags, [])
        return prog, list(prog.collections[coll].fields)

    def test_one_sentence(self):
        for text in ['Customers is a collection where each customer has a name, an age and an email.',
                     'Customers is a collection with a name, an age and an email.',
                     'Customers are a collection of people who have a name, an age and an email.',
                     'Each customer has a name, an age and an email.',
                     'Customers have a name, an age and an email.']:
            with self.subTest(text):
                self.assertEqual(self.fields(text, 'customer')[1], ['name', 'age', 'email'])

    def test_describing_does_not_swallow_a_typo(self):
        self.assertNotIn('custmer', parse(BASE + 'Each custmer has a phone.')[0].collections)

    def test_plural_means_several(self):
        prog, _ = self.fields('Contacts have a name and phones.\nNames are unique.\n', 'contact')
        self.assertEqual(list(prog.collections['contact'].fields), ['name'])
        link = prog.collections['phone'].fields['contact']
        self.assertEqual((link.ref, link.on_removed), ('contact', 'cascade'))
        self.assertTrue(any('several values' in d.msg for d in parse('Contacts have a name and phones.\n')[1]))

    def test_ways_to_say_one_or_several(self):
        for text, several in [('Each team has a title and several tags.', True),
                              ('Each team has a title and a list of tags.', True),
                              ('Each team has a title and one or more tags.', True),
                              ('Each team has a title and tags.', True),
                              ('Each team has a title and a tag.', False),
                              ('Each team has a title and tags (text).', False),
                              ('Each team has a title and points.', False)]:
            with self.subTest(text):
                prog, _, _ = parse(text + '\nTitles are unique.\n')
                self.assertEqual(len(prog.collections) == 2, several)

    def test_has_orders_links_an_existing_collection(self):
        prog, _, _ = parse('Customers have a name.\nNames are unique.\nOrders have an id (number).\n'
                           'Each customer has orders.\n')
        self.assertEqual(prog.collections['order'].fields['customer'].ref, 'customer')
        self.assertNotIn('order', prog.collections['customer'].fields)

    def test_readings(self):
        base = MANY.split('Add a contact.')[0]
        for text, want in [('Add a phone to a given contact.', 'add phone'),
                           ('Show the phones of a given contact.', 'list all of phone where contact == <contact>'),
                           ('Show the phones whose phone starts with "555".',
                            'list all of phone where phone starts with "555"'),
                           ("Show the phone and the contact's name of phones.", 'list phone, contact.name of phone')]:
            with self.subTest(text):
                self.assertEqual(meaning(text, base), want)

    def test_native(self):
        self.differential('many', MANY, seeds=5, n=500)



class TestThinking(TestNativeAgainstReference):
    """Calculations that decide, single values, and rules that apply by themselves."""

    def run_ref(self, text, cmds):
        prog, diags, _ = understand('', text)
        self.assertEqual([d.msg for d in diags], [])
        m = Machine(prog)
        return [o for c in cmds for o in m.run(c)]

    def test_one_letter_inputs(self):
        for text in ['Sum: take a number a and a number b and return a plus b.',
                     'Sum: take two numbers a and b and return a plus b.',
                     'Sum: take a and b and return a plus b.',
                     'Sum: take a and b, then return a + b.']:
            with self.subTest(text):
                self.assertEqual(meaning(text, ''), 'calc(a, b) = <a> + <b>')

    def test_either_or_value(self):
        want = 'calc(a, b) = <a> if <a> > <b> else <b>'
        for text in ['Bigger: take a and b and return a if a is over b, otherwise b.',
                     'Bigger: take a and b and return a when a is more than b, else b.',
                     'Bigger: take a and b, if a is greater than b then return a, otherwise return b.',
                     'Bigger: take a and b and give back a if a > b or else b.']:
            with self.subTest(text):
                self.assertEqual(meaning(text, ''), want)
        self.assertEqual(meaning('Sign: take n and return 1 if n is over 0, otherwise -1 if n is under 0, otherwise 0.', ''),
                         'calc(n) = 1 if <n> > 0 else (-1 if <n> < 0 else 0)')

    def test_half_a_decision_is_a_question(self):
        level, at, d = problem('Bigger: take a and b and return a if a is over b.', '')
        self.assertEqual((level, d.msg), ('question', 'and what if not?'))

    def test_division_asks_about_zero(self):
        level, _, d = problem('Share: take a and b and return a divided by b.', '')
        self.assertEqual((level, d.msg), ('question', 'what should happen when the given b is zero?'))
        for ok in ['Share: take a and b and return a divided by b if b is not 0, otherwise 0.',
                   'Share: take a and b and return 0 if b is 0, otherwise a divided by b.',
                   'Share: take a and b and return a divided by b if b is over 0, otherwise 1.']:
            with self.subTest(ok):
                self.assertEqual(understand(ok, '')[1], [])
        self.assertEqual(understand('Halve the salary if the age is not 0.')[1], [])
        self.assertEqual(understand('Divide the salary by the age if the age is not 0.')[1], [])

    def test_either_or_in_a_change(self):
        self.assertEqual(meaning('Set the salary to 100 if the age is over 30, otherwise 50.'),
                         'update customer: salary = 100 if age > 30 else 50')
        self.assertEqual(meaning('Set the salary to 100 if the age is over 30, otherwise set the salary to 50.'),
                         'update customer: salary = 100 if age > 30 else 50')
        self.assertEqual(problem('Show the customers, otherwise 5.')[0], 'error')

    def test_declaring_values(self):
        for text, typ, init in [('The score is a number.', 'int', 0), ('The score starts at 7.', 'int', 7),
                                ('The score is 7.', 'int', 7), ('The title is text.', 'text', ''),
                                ('The high score is a number that starts at 3.', 'int', 3),
                                ('The mood starts as "calm".', 'text', 'calm')]:
            with self.subTest(text):
                prog, diags, _ = understand(text, '')
                self.assertEqual(diags, [])
                f = next(iter(prog.collections['(values)'].fields.values()))
                self.assertEqual((f.type, f.init), (typ, init))
        prog, diags, _ = understand('The score is a number. The scroe starts at 5.', '')    # a slip, not a new value
        self.assertEqual((diags, [(f.name, f.init) for f in prog.collections['(values)'].fields.values()]),
                         ([], [('score', 5)]))
        self.assertEqual(problem('The age is 5.')[0], 'error')

    def test_using_values(self):
        base = 'The score starts at 2.\nThe limit is 30.\n'
        self.assertEqual(meaning('Bump: increase the score by a given amount.', base), 'set score = score + <amount>')
        self.assertEqual(meaning('Double the score.', base), 'set score = score * 2')
        self.assertEqual(meaning('Show the score and the limit.', base), 'show score, limit')
        self.assertEqual(meaning('Show customers whose age is over the limit.', BASE + base),
                         'list all of customer where age > limit')
        self.assertEqual(problem('Remove the score.', base)[0], 'error')
        prog, _, _ = understand('Bump: increase the score by a given amount. Show the score.', base)
        self.assertEqual([t.name for t in prog.tasks], ['bump', 'score'])

    def test_rules_are_not_commands(self):
        base = BASE + 'The best starts at 0.\n'
        for text, want in [('When a customer\'s age is over 64, their salary becomes 0.',
                            'update customer: salary = 0 where age > 64'),
                           ('Whenever the age of a customer is over 64, set the salary to 0.',
                            'update customer: salary = 0 where age > 64'),
                           ('As soon as a customer\'s salary is under 0, remove them.',
                            'remove customer where salary < 0'),
                           ('The best is always 10 if a given x is under 10, otherwise 20.', None),
                           ('When the best is under 5, the best becomes 5.', 'set best = 5 where best < 5')]:
            with self.subTest(text):
                prog, diags, _ = understand(text, base)
                if want is None:
                    self.assertEqual([d.level for d in diags], ['error'])
                    continue
                self.assertEqual(diags, [])
                self.assertEqual((prog.tasks, [canon(r) for r in prog.rules]), ([], [want]))
        # a name makes it a capability again
        prog, _, _ = understand('Retire: when a customer\'s age is over 64, their salary becomes 0.', base)
        self.assertEqual((len(prog.tasks), len(prog.rules)), (1, 0))

    def test_a_rule_must_come_to_rest(self):
        level, _, d = problem('When a customer\'s age is under 18, increase the age by 1.')
        self.assertEqual(level, 'error')
        self.assertIn('again every time', d.msg)
        self.assertEqual(problem('When the age is over 5, show the customers.')[0], 'error')

    def test_rules_apply_until_nothing_changes(self):
        text = ('The score starts at 0. The level starts at 1. The mood starts as "calm".\n'
                'Hit: increase the score by a given amount. Status: show the score, the level and the mood.\n'
                'When the level is 2, the mood becomes "excited".\n'       # written first, still follows
                'When the score is at least 10, the level becomes 2.\n')
        self.assertEqual(self.run_ref(text, ['status', 'hit 4', 'status', 'hit 6', 'status']),
                         ['0,1,calm', '4,1,calm', '10,2,excited'])

    def test_rules_that_fight_are_reported(self):
        text = ('The x starts at 0. Poke: set the x to 1.\n'
                'When the x is 1, the x becomes 2. When the x is 2, the x becomes 1.')
        self.assertEqual(self.run_ref(text, ['poke']), ['error: the rules keep changing each other'])
        self.differential('fight', text, seeds=1, n=5)

    def test_rules_hold_from_the_start(self):
        text = 'The floor starts at 3. The x starts at 0. Show the x. When the x is under the floor, the x becomes the floor.'
        self.assertEqual(self.run_ref(text, ['x']), ['3'])
        self.differential('start', text, seeds=1, n=5)

    def test_calculator_natively(self):
        with open(os.path.join(ROOT, 'examples', 'calculator.intent')) as fh:
            self.differential('calculator', fh.read(), seeds=4, n=400)

    def test_arcade_natively(self):
        with open(os.path.join(ROOT, 'examples', 'arcade.intent')) as fh:
            self.differential('arcade', fh.read(), seeds=6, n=400)

    def test_rules_over_related_records_natively(self):
        self.differential('rules', (
            'Customers have a unique name and a balance. Reject duplicates.\n'
            'Orders have a number (number), a total and a state (text). Each order belongs to a customer.\n'
            'When a customer is removed, remove its orders.\n'
            'The limit starts at 50.\n'
            'Add a customer. Add an order. Remove a customer by name.\n'
            'Charge: increase the balance of the customer with a given name by a given amount.\n'
            'Raise: set the limit to a given amount.\n'
            'Show the customers. Show the orders. Show the limit.\n'
            'Mark: set the state to "big" if the total is over the limit, otherwise "small".\n'
            'Whenever a customer\'s balance is under 0, remove them.\n'
            'When an order\'s total is over 100, its state becomes "huge".\n'
            'When the limit is under 10, the limit becomes 10.'), seeds=6, n=400)

    def test_values_are_remembered(self):
        src, exe = os.path.join(self.dir, 'v.intent'), os.path.join(self.dir, 'v')
        log = os.path.join(self.dir, 'v.log')
        with open(src, 'w') as fh:
            fh.write('The score starts at 5. The best starts at 0. Hit: increase the score by a given amount. '
                     'Show the score and the best. When the score is over the best, the best becomes the score.')
        build(src, exe, quiet=True)

        def run(text):
            return subprocess.run([exe, log], input=text, capture_output=True, text=True).stdout

        self.assertEqual(run('score-best\nhit 4\n'), '5,5\n')
        self.assertEqual(run('hit -7\nscore-best\n'), '2,9\n')


GAME = ('The score is a number. The lives start at 3. The column starts at 3.\n'
        'Rocks is a collection where each rock has an x (number) and a y (number).\n')


class TestLive(TestNativeAgainstReference):
    def run_ref(self, text, cmds):
        prog, diags, _ = understand('', text)
        self.assertEqual([d.msg for d in diags], [])
        m = Machine(prog)
        return [o for c in cmds for o in m.run(c)]

    def events(self, text, base=GAME):
        prog, diags, _ = understand(text, base)
        self.assertEqual([d.msg for d in diags], [], text)
        return [(t.on, canon(t)) for t in prog.events]

    def test_time_phrasings(self):
        for text, ms in [('Every second, the score increases by 1.', 1000),
                         ('Each second the score increases by 1.', 1000),
                         ('The score increases by 1 every second.', 1000),
                         ('Every 2 seconds, increase the score by 1.', 2000),
                         ('Every two seconds, add 1 to the score.', 2000),
                         ('Every 250 milliseconds, the score goes up by 1.', 250),
                         ('Every 250 ms, the score increases by 1.', 250),
                         ('4 times a second, the score increases by 1.', 250),
                         ('Twice a second, the score rises by 1.', 500),
                         ('Every minute, the score increases by 1.', 60000)]:
            with self.subTest(text):
                self.assertEqual(self.events(text), [(('every', ms), 'set score = score + 1')])
        self.assertEqual(self.events('Every second, the y of each rock increases by 1.'),
                         [(('every', 1000), 'update rock: y = y + 1')])
        self.assertEqual(self.events('Every second, remove the rocks whose y is over 9.'),
                         [(('every', 1000), 'remove rock where y > 9')])

    def test_key_phrasings(self):
        for text in ['When the left key is pressed, the column decreases by 1.',
                     'When left is pressed, decrease the column by 1.',
                     'Whenever the left arrow key is pressed, the column decreases by 1.',
                     'When the player presses left, the column decreases by 1.',
                     'If the player presses the left arrow, the column goes down by 1.',
                     'The column decreases by 1 when the left key is pressed.',
                     'The column decreases by 1 when the player hits left.']:
            with self.subTest(text):
                self.assertEqual(self.events(text), [(('key', 'left'), 'set column = column - 1')])
        self.assertEqual(self.events('When the a key is pressed, the score doubles.'),
                         [(('key', 'a'), 'set score = score * 2')])
        self.assertEqual(self.events('When return is pressed, the score becomes 0 if the lives are over 0.'),
                         [(('key', 'enter'), 'set score = 0 where lives > 0')])

    def test_what_cannot_happen_by_itself(self):
        for text, msg in [('Every second, show the score.', 'what should change?'),
                          ('Every second, increase the score by a given amount.',
                           'there is nobody to give the amount here'),
                          ('Tick: every second, the score increases by 1.',
                           'this happens by itself, so it needs no name'),
                          ('When the banana key is pressed, the score becomes 0.',
                           'I don\'t know a key called "banana"'),
                          ('Every 0.5 seconds, the score increases by 1.', 'decimal numbers are not supported yet'),
                          ('Every 90 minutes, the score increases by 1.',
                           'this has to be between one millisecond and one hour'),
                          ('The game is over.', 'when is the game over?'),
                          ('The board is 30 wide.', 'how high is the board?'),
                          ('The board is 30 wide and 500 high.',
                           'a board can be at most 200 wide and 60 high in this version'),
                          ('Draw each rock as "#".', 'where should it be drawn?'),
                          ('Draw each rock at its x and y.', 'what should it look like?'),
                          ('Draw each rock at its x and y as "##".', 'one thing is drawn as one plain character'),
                          ('Draw each rock at its x and y as "#".', 'how big is the board this is drawn on?'),
                          ('The board is 9 by 9. Show the rocks above the board.',
                           'only single values can be shown beside the board in this version'),
                          ('Start with a rock at x 3.', 'what is the y of this rock?')]:
            with self.subTest(text):
                self.assertEqual(problem(text, GAME + 'Drop: add a rock.\n')[2].msg, msg)

    def test_slips_in_the_new_sentences(self):
        prog, diags, _ = understand('Evry secnd, the score increases by 1. When space is presed, the score becomes 0.',
                                    GAME)
        self.assertEqual((diags, [t.on for t in prog.events]), ([], [('every', 1000), ('key', 'space')]))

    def test_the_new_words_are_not_reserved(self):
        prog, diags, _ = understand('The high score starts at 9. Each ticket has a key (text), a board (text) and '
                                    'seconds. Add a ticket. Show the tickets whose seconds are over 3.', '')
        self.assertEqual(diags, [])
        self.assertEqual(list(prog.collections['ticket'].fields), ['key', 'board', 'second'])
        self.assertEqual(canon(prog.tasks[-1]), 'list all of ticket where second > 3')

    def test_board_and_drawing(self):
        for text in ['The board is 30 wide and 12 high.', 'Show a board 30 wide and 12 high.',
                     'The screen is 30 by 12.', 'The grid has 30 columns and 12 rows.']:
            with self.subTest(text):
                self.assertEqual(understand(text, GAME)[0].board, (30, 12))
        prog, diags, _ = understand(
            'The board is 30 by 12. Draw each rock whose y is over 2 at its x and its y plus 1 as "o". '
            'Draw @ at the column and 12. Show the score and the lives above the board. '
            'Show the column below the board.', GAME)
        self.assertEqual(diags, [])
        self.assertEqual([(d.coll, d.at, d.glyph, d.where) for d in prog.draws],
                         [('rock', (('field', 'x'), ('bin', 'add', ('field', 'y'), ('num', 1))), 'o',
                           ('cmp', 'gt', ('field', 'y'), ('num', 2))),
                          (None, (('value', 'column'), ('num', 12)), '@', None)])
        self.assertEqual((prog.above, prog.below), (['score', 'lives'], ['column']))
        prog, diags, _ = understand('Rocks have an x and a y. The board is 9 by 9. Draw each rock at its x and y as "#".', '')
        self.assertEqual((diags, {prog.collections['rock'].fields[f].type for f in 'xy'}), ([], {'int'}))

    def test_endings_and_starting_records(self):
        for text in ['The game is over when the lives are under 1.', 'The game ends when the lives are under 1.',
                     'When the lives are under 1, the game is over.', 'Once the lives are under 1 the game ends.']:
            with self.subTest(text):
                e, = understand(text, GAME)[0].ends
                self.assertEqual((e.coll, e.where), ('(values)', ('cmp', 'lt', ('field', 'lives'), ('num', 1))))
        e, = understand('The game is over when any rock has an x equal to the column and a y equal to 4.',
                        GAME)[0].ends
        self.assertEqual((e.coll, e.where), ('rock', ('and', ('cmp', 'eq', ('field', 'x'), ('value', 'column')),
                                                      ('cmp', 'eq', ('field', 'y'), ('num', 4)))))
        for text in ['Start with a rock at x 4, y 1.', 'There is a rock whose x is 4 and whose y is 1.',
                     'At the start there is a rock with x 4 and y 1.', 'To begin with a rock has x 4, y 1.']:
            with self.subTest(text):
                s, = understand(text, GAME)[0].seeds
                self.assertEqual(s.assigns, [('x', ('num', 4)), ('y', ('num', 1))])
        self.assertEqual(problem('Players have a unique name. Reject duplicates. Add a player. '
                                 'Start with a player whose name is "ann". There is a player whose name is "ann".',
                                 '')[2].msg, 'two players would start with the same name')

    def test_time_is_exact(self):
        text = ('The slow starts at 0. The fast starts at 0. The log starts at 0. Show the slow, the fast and the log.\n'
                'Every 300 milliseconds, the slow increases by 1.\n'
                'Every 200 milliseconds, the fast increases by 1.\n'
                'Every 600 milliseconds, the log becomes the slow times 10 plus the fast.\n')
        got = self.run_ref(text, ['wait 199', 'slow-fast-log', 'wait 1', 'slow-fast-log', 'wait 400', 'slow-fast-log',
                                  'wait 0', 'wait 5000', 'slow-fast-log', 'wait -1', 'wait', 'wait 2x', 'press left'])
        self.assertEqual(got, ['0,0,0', '0,1,0', '2,3,23', '18,28,207',
                               'error: wait takes a number of milliseconds, from 0 to 3600000'] * 1 +
                         ['error: wait takes a number of milliseconds, from 0 to 3600000'] * 2 +
                         ['error: unknown command press'])

    def test_game_over_stops_time_and_keys(self):
        text = ('The lives start at 2. The score is a number. Show the lives and the score.\n'
                'Every second, the lives decrease by 1. Every second, the score increases by 1.\n'
                'When the space key is pressed, the score doubles.\n'
                'The game is over when the lives are under 1. Again: set the lives to 2.\n')
        self.assertEqual(self.run_ref(text, ['press space', 'wait 5000', 'lives-score', 'wait 1000', 'press space',
                                             'press x', 'again', 'press space', 'wait 1000', 'lives-score']),
                         ['0,2', 'the game is over', 'the game is over',
                          'error: no key called x is used here', '1,5'])

    def script(self, name, text, cmds):
        """The native program and the reference must print the same thing for the same events."""
        src, exe = os.path.join(self.dir, name + '.intent'), os.path.join(self.dir, name)
        with open(src, 'w') as fh:
            fh.write(text)
        prog = build(src, exe, quiet=True)
        self.assertIsNotNone(prog, 'did not compile')
        m = Machine(prog)
        expected = [line for c in cmds for line in m.run(c)]
        got = subprocess.run([exe], input='\n'.join(cmds) + '\n', capture_output=True, text=True, timeout=60)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(got.stdout.split('\n')[:-1], expected)
        return exe, expected

    def dodge(self):
        with open(os.path.join(ROOT, 'examples', 'dodge.intent')) as fh:
            return fh.read()

    def test_dodge_natively(self):
        for seed in range(5):
            rng = random.Random(seed)
            cmds = ['help', 'screen']
            for _ in range(300):
                cmds.append(rng.choice([f'wait {rng.choice([0, 1, 37, 149, 150, 151, 400, 1000, 2500])}',
                                        'press left', 'press right', 'press up', 'screen', 'wait', 'column-row-score'
                                        if False else 'screen']))
            self.script('dodge', self.dodge(), cmds)

    def test_live_program_natively(self):
        text = ('The board is 12 by 6. The px starts at 6. The py starts at 3. The score is a number. '
                'The title starts as "go". Show the score and the title above the board. '
                'Show the px below the board.\n'
                'Coins have an x, a y and a worth. Reject duplicates. Drop: add a coin. Show the coins.\n'
                'Start with a coin at x 2, y 2, worth 5.\n'
                'Every 100 milliseconds, the x of each coin increases by 1.\n'
                'Every 300 milliseconds, remove the coins whose x is over 12.\n'
                'Every 700 ms, the score increases by the px.\n'
                'When w is pressed, the py decreases by 1 if the py is over 1.\n'
                'When s is pressed, the py increases by 1 if the py is under 6.\n'
                'When the space key is pressed, the worth of each coin doubles.\n'
                'When the score is over 20, the title becomes "far".\n'
                'The game ends when the score is over 60.\n'
                'The game is over when any coin has a worth over 1000.\n'
                'Draw each coin whose worth is over 5 at its x and y as "O". '
                'Draw each coin whose worth is at most 5 at its x and y as "o".\n'
                'Draw "@" at the px and the py.\n')
        for seed in range(5):
            rng = random.Random(seed)
            cmds = []
            for _ in range(300):
                cmds.append(rng.choice([f'wait {rng.choice([0, 50, 99, 100, 101, 250, 700])}', 'press w', 'press s',
                                        'press space', 'screen', 'list',
                                        f'drop {rng.randint(-2, 14)},{rng.randint(0, 7)},{rng.randint(1, 9)}']))
            self.script('live', text, cmds)

    def test_a_game_is_remembered_and_replayed(self):
        exe, _ = self.script('dodge', self.dodge(), ['screen'])
        log = os.path.join(self.dir, 'dodge.log')
        first = ['wait 450', 'press left', 'press left', 'wait 1200']

        def run(cmds):
            return subprocess.run([exe, log], input='\n'.join(cmds) + '\n', capture_output=True, text=True).stdout
        run(first)
        with open(log) as fh:
            self.assertEqual(fh.read().split('\n')[:-1], first)
        whole = subprocess.run([exe], input='\n'.join(first + ['screen']) + '\n', capture_output=True, text=True)
        self.assertEqual(run(['screen']), whole.stdout)

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_playing_in_a_terminal(self):
        import pty
        import re
        import select
        import time
        exe, _ = self.script('walk', (
            'The board is 30 wide and 3 high. The column starts at 15. The score is a number.\n'
            'Every 200 milliseconds, the score goes up by 1.\n'
            'When the left key is pressed, the column decreases by 1.\n'
            'When the right key is pressed, the column increases by 1.\n'
            'Draw "@" at the column and 2. Show the score above the board.\n'), ['screen'])
        for cmd in ([exe], [sys.executable, os.path.join(ROOT, 'intent'), 'run', os.path.join(self.dir, 'walk.intent')]):
            with self.subTest(cmd[0]):
                pid, fd = pty.fork()
                if pid == 0:
                    os.execv(cmd[0], cmd)
                out = b''

                def pump(seconds):
                    nonlocal out
                    end = time.time() + seconds
                    while time.time() < end:
                        if select.select([fd], [], [], 0.05)[0]:
                            try:
                                out += os.read(fd, 65536)
                            except OSError:
                                return
                pump(1.6)
                for key in (b'\x1b[D', b'\x1b[D', b'\x1b[C', b'\x1b[D'):
                    os.write(fd, key)
                    pump(0.15)
                os.write(fd, b'q')
                pump(0.5)
                _, status = os.waitpid(pid, 0)
                os.close(fd)
                self.assertEqual(status, 0)
                frames = [re.sub(r'\x1b\[[0-9?]*[A-Za-z]', '', f).replace('\r', '')
                          for f in out.decode().split('\x1b[H')[1:]]
                self.assertGreater(len(frames), 8)                  # time passed without any key
                self.assertTrue(frames[0].startswith('score 0\n+' + '-' * 30 + '+\n'))
                self.assertGreater(int(frames[-1].split('\n')[0].split()[1]), 5)    # the clock really ran
                player = [line.index('@') for line in frames[-1].split('\n') if '@' in line]
                self.assertEqual(player, [13])                      # from 15: two left, one right, one left


if __name__ == '__main__':
    unittest.main()
