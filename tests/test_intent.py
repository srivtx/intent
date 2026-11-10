"""Tests for the four claims the prototype makes.

  1. Many phrasings, one meaning           (TestPhrasings)
  2. Never guess: ask, pointing at the words (TestQuestions)
  3. Representation follows declared behaviour (TestPlanner)
  4. Native code means what the reference interpreter says (TestNativeAgainstReference)
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
        self.assertEqual(problem('Divide the salary by the age.')[0], 'error')

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
    out = []
    for _ in range(n):
        t = rng.choice(prog.tasks)
        if t.kind == 'add' and rng.random() < 0.5:
            t = rng.choice([x for x in prog.tasks if x.kind == 'add'])
        args = []
        for p in t.params:
            if t.ptypes[p] == 'int':
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
                if not ordered and t.kind in ('list', 'find'):
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


if __name__ == '__main__':
    unittest.main()
