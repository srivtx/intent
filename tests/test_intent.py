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
 13. Colour, chance, records that appear, hits, steps, restarting  (TestLive, from test_colour_phrasings on)
 14. One record is found through the index; rules look only where needed (TestLive.test_one_record_*)
 15. Counting and matching across collections, word order, numbered names (TestAcross)
 16. The same commands over the network, and a window                  (TestNetwork)
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
from intentc.ir import STATE, canon, fmt_cond   # noqa: E402
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
    'decimal_money': '''
Products is a collection. Each product has a code (number), a name, a price (money) and a stock (number).
Codes are unique. Reject duplicates.
The till starts at 0.00. The rate is a decimal starting at 1.08.
Add a product. Find a product by code. Remove a product by code. Show all products.
sale: decrease the price by a given discount for products whose stock is over 3.
markup: multiply the price by the rate for products whose price is under a given limit.
halve: set the price to price divided by 2 for every product.
cheap: show the names of products whose price is at most 10.5.
total price
average price
largest price
smallest price of products whose stock is over 2
by-price: show products sorted by price, lowest first.
sell: increase the till by a given amount.
share: take a decimal bill and a number n and return bill divided by n if n is not 0, otherwise 0.
tax: take a decimal p and return p times 0.2 plus 1.
show the till.
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
            if p in t.pdec:
                args.append(rng.choice([f'{rng.randint(0, 40)}.{rng.randint(0, 99):02d}', str(rng.randint(-5, 30)),
                                        f'-{rng.randint(0, 3)}.{rng.randint(0, 9)}', '0.05', '-0.05', '99999999999999999',
                                        '-92233720368547758.08', '1.234', '.5', ' 2.5', '3.', '12.50']))
            elif t.ptypes[p] == 'int' and p in small and rng.random() < 0.85:
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

    def test_decimal_money(self):
        self.differential('d', PROGRAMS['decimal_money'])

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



class TestDecimals(TestNativeAgainstReference):
    """Decimal numbers (money): kept exactly as hundredths, rounded half away from zero."""
    SHOP = ('Products is a collection. Each product has a code (text), a price (money) and a stock (number).\n'
            'Codes are unique. Reject duplicates.\n')

    def run_ref(self, text, cmds):
        prog, diags, _ = understand('', text)
        self.assertEqual([d.msg for d in diags], [])
        m = Machine(prog)
        return [o for c in cmds for o in m.run(c)]

    def test_declaring_decimals(self):
        for words in ['a price (money)', 'a price (decimal)', 'a price (decimal number)', 'a price (currency)',
                      'a decimal price', 'a price as money']:
            prog, diags, _ = understand('', f'Products is a collection. Each product has a code (text) and {words}.')
            self.assertEqual(diags, [])
            self.assertTrue(prog.collections['product'].fields['price'].dec, words)
        prog, diags, _ = understand('', 'The till starts at 0.00. The rate is a decimal starting at 1.08. Show the till.')
        S = prog.collections[STATE].fields
        self.assertEqual((S['till'].dec, S['till'].init, S['rate'].init), (True, 0, 108))

    def test_exact_arithmetic(self):
        text = self.SHOP + ('Add a product. Find a product by code.\n'
                            'sale: decrease the price by a given discount for products whose stock is over 3.\n'
                            'What is the total price? What is the average price?\n'
                            'share: take a decimal bill and a number n and return bill divided by n if n is not 0, otherwise 0.\n'
                            'tax: take a decimal p and return p times 0.08.\n')
        self.assertEqual(self.run_ref(text, ['add a,12.50,10', 'add b,0.1,1', 'add c,0.2,1', 'sale 1.25',
                                             'find-by-code a', 'total-price', 'average-price',
                                             'share 100,3', 'share 0.05,2', 'share -0.05,2', 'share 1,0',
                                             'tax 0.10', 'tax 9.99', 'add d,1.234,1', 'add e,.5,1']),
                         ['a,11.25,10', '11.55', '3.85', '33.33', '0.03', '-0.03', '0.00', '0.01', '0.80',
                          'error: price must be a number like 12.50', 'error: price must be a number like 12.50'])

    def test_a_given_amount_takes_the_kind_it_meets(self):
        prog, diags, _ = understand('', self.SHOP + 'Add a product. sale: decrease the price by a given discount '
                                                    'for every product. bump: increase the stock by a given n for every product.')
        tasks = {t.name: t for t in prog.tasks}
        self.assertEqual((tasks['sale'].pdec, tasks['bump'].pdec), ({'discount'}, set()))

    def test_what_decimals_cannot_do(self):
        for line, msg in [('bump: increase the stock by 0.5 for every product.',
                           '"stock" is a whole number, and this would give it a decimal one'),
                          ('r: take a decimal p and return p mod 3.', 'the remainder of a decimal number is not supported yet'),
                          ('bad: show the codes of products whose price is over 1.234.',
                           'a decimal number has one or two digits after the point')]:
            prog, diags, _ = understand('', self.SHOP + 'Add a product. ' + line)
            self.assertEqual([d.msg for d in diags], [msg], line)

    def test_decimal_division_has_no_remainder_note(self):
        prog, diags, p = parse('Products is a collection. Each product has a price (money). Add a product. '
                               'h: set the price to price divided by 2 for every product.')
        diags += check(prog, p.src)
        self.assertFalse(any('drops the remainder' in d.msg for d in diags))

    def test_native_prints_and_parses_the_same(self):
        self.differential('money', self.SHOP + (
            'The till starts at 0.00. Add a product. Find a product by code. Show all products.\n'
            'sell: increase the till by a given amount. Show the till.\n'
            'markup: multiply the price by 1.15 for products whose price is under a given limit.\n'
            'What is the largest price? What is the smallest price?\n'), seeds=4, n=300)


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
                          ('Every 0.0005 seconds, the score increases by 1.', 'this is not a whole number of milliseconds'),
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

    def test_no_stray_word_is_ignored(self):
        """Every one of these compiled before the sentences were tightened."""
        for text in ['The board is draw 30 wide and 12 high.', 'The board board is 30 wide and 12 high.',
                     'The board is 30 wide wide and 12 high.', 'The board is 30 by by 12.', 'The board is x 30 by 12.',
                     'When the left key key is pressed, the score becomes 0.',
                     'When the left key is is pressed, the score becomes 0.',
                     'The board is 9 by 9. Draw x each rock at its x and y as "#".',
                     'The board is 9 by 9. Draw score "@" at the column and 2.',
                     'The is game is over when the lives are 0.',
                     'Start with a rock at x is is 4, y 1.', 'Start with a rock at x when 4, y 1.',
                     'The board is 9 by 9. Show the score the lives above the board.',
                     'Every second, remove the rocks whose y is over under 3.',
                     'The game is over when any rock has an x over equal to the column.',
                     'The total when starts at 15.', 'The total starts at when 15.']:
            with self.subTest(text):
                _, diags, _ = understand(text, GAME + 'Drop: add a rock.\n')
                self.assertTrue(diags, 'compiled, so a word was ignored')
        level, where, d = problem('Show the rocks whose y is over under 3.', GAME)
        self.assertEqual((level, where, d.msg), ('question', 'over under', '"over" or "under"?'))
        prog, diags, _ = understand('Coins is a collection where score each coin has a worth (number). Add a coin.', GAME)
        self.assertEqual(diags[0].msg, 'I don\'t see how "score" fits in')

    def test_mangled_games_never_crash_the_compiler(self):
        """Delete, insert, swap and cut words at random: the answer is a diagnosis or a program, never a traceback."""
        from intentc.source import strip_comment
        extra = ['every', 'second', 'when', 'pressed', 'key', 'the', 'at', 'as', 'board', 'draw', 'game', 'over',
                 'is', '"#"', '3', 'and', 'its', 'left', 'start', 'with', 'each', 'if', 'by', 'wide', '@', ':', ',']
        lines = [strip_comment(line) for line in self.dodge().split('\n')]
        full = [i for i, line in enumerate(lines) if line.strip()]
        rng = random.Random(7)
        compiled = 0
        for _ in range(150):
            mangled = list(lines)
            for _ in range(rng.choice([1, 2, 4])):
                i = rng.choice(full)
                w = mangled[i].split() or ['x']
                j, k = rng.randrange(len(w)), rng.randrange(len(w))
                op = rng.randrange(6)
                if op == 0:
                    del w[j]
                elif op == 1:
                    w.insert(j, rng.choice(extra))
                elif op == 2:
                    w[j] = rng.choice(extra)
                elif op == 3:
                    w[j], w[k] = w[k], w[j]
                else:
                    w = w[:j] if op == 4 else w[j:]
                mangled[i] = ' '.join(w)
            prog, diags, _ = understand('\n'.join(mangled), '')
            if not diags:
                compiled += 1
                make_plan(prog)
                m = Machine(prog)
                for c in ['help', 'wait 1000', 'screen', 'press left', 'wait 77', 'screen']:
                    m.run(c)
        self.assertGreater(compiled, 3)

    def test_odd_programs_natively(self):
        cmds = ['help', 'wait 0', 'wait 1', 'wait 7', 'wait 13', 'wait 999', 'wait 3600000', 'wait 3600001', 'wait -5',
                'wait', 'wait  5', 'wait 5 ', 'wait +5', 'wait 1e3', 'wait 99999999999999999999', 'press up', 'press 7',
                'press enter', 'press q', 'press r', 'press', 'press  up', 'press UP', 'press left', 'screen',
                'screen 4', 'n', 'bump 3', 'bump -9', 'add 2,1', 'add 5,2', 'add 9', 'add zed,4', 'add ann,1',
                'remove-by-name ann', 'list', 'find-by-name bob', 'wait 4,5', 'again', 'clear', 'mood-turn', '']
        programs = {
            'timers': 'The n starts at 0. Show the n. Every 7 ms, the n increases by 1. Every 7 ms, the n doubles. '
                      'When the n is over 1000, the n becomes 0.',
            'keys': 'The n starts at 1. Show the n. When up is pressed, the n triples. When 7 is pressed, the n '
                    'becomes 7. When the enter key is pressed, the n decreases by 1.',
            'tiny': 'The board is 1 by 1. The n starts at 1. Draw "x" at the n and 1. Bump: increase the n by a '
                    'given amount.',
            'novalues': 'The board is 5 by 2. Dots have an x and a y. Add a dot. Draw each dot at its x and its y '
                        'as "." . Draw "%" at 5 and 2. Draw "\\" at 1 and 1.',
            'taken': 'The n starts at 0. Wait: increase the n by a given amount. Screen: show the n. Press: set the '
                     'n to 5. Every second, the n increases by 1. When q is pressed, the n becomes 9. '
                     'The board is 3 by 1. Draw "n" at the n and 1.',
            'status': 'The board is 6 by 1. The mood starts as "calm". The high_score starts at 3. The turn is a '
                      'number. Show the mood and the turn above the board. Show the high_score below the board. '
                      'Every second, the turn increases by 1. When the turn is over 2, the mood becomes "wild". '
                      'Draw "*" at the turn and 1.',
            'stuck': 'The n starts at 0. Show the n. Every second, the n increases by 1. When the n is 2, the n '
                     'becomes 3. When the n is 3, the n becomes 2.',
            'ends': 'The n starts at 0. Show the n. Rocks have a y. Add a rock. Every 10 ms, the n increases by 1. '
                    'Every 10 ms, the y of each rock increases by the n. The game ends when the n is over 20. '
                    'The game is over when any rock has a y over 50. When r is pressed, the n becomes 0. '
                    'Again: set the n to 0. Clear: remove the rocks whose y is over 0.',
            'seeds': 'Players have a unique name and points. Reject duplicates. Keep the players in the order they '
                     'were added. Start with a player whose name is "ann" and whose points are 3. Start with a '
                     'player with name "bob", points 9. Add a player. Find a player by name. Remove a player by '
                     'name. Show the players. Every second, the points of each player increase by 1. '
                     'Every 3 seconds, remove the players whose points are over 12.',
            'wrap': 'The n starts at 9000000000000000000. Show the n. Every ms, the n increases by the n. The '
                    'board is 4 by 2. Draw "o" at the n and the n divided by 2. Draw "p" at 2 minus the n and 1.',
        }
        for name, text in programs.items():
            with self.subTest(name):
                rng = random.Random(name)
                self.script(name, text, [rng.choice(cmds) for _ in range(250)])

    def in_a_terminal(self, cmd, keys, rows=30, cols=80, settle=0.3):
        """Run cmd on a pseudo-terminal of the given size, type keys (bytes, or a signal number), and report.

        Nothing is typed before the game is on screen, and nothing here waits without a deadline:
        a program that does not stop is killed and the test fails with what it printed.
        """
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        import time
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        before = termios.tcgetattr(master)
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                for fd in (0, 1, 2):
                    os.dup2(slave, fd)
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
                os.execv(cmd[0], cmd)
            finally:
                os._exit(127)           # never fall back into the test runner
        os.close(slave)
        out = b''
        status = None

        def pump(seconds, until=lambda: False):
            nonlocal out, status
            end = time.time() + seconds
            while time.time() < end and not until():
                if select.select([master], [], [], 0.02)[0]:
                    try:
                        out += os.read(master, 65536)
                    except OSError:
                        pass
                if status is None:
                    done, st = os.waitpid(pid, os.WNOHANG)
                    if done:
                        status = st
                elif not select.select([master], [], [], 0.05)[0]:
                    return
        pump(20, lambda: b'\x1b[?1049h' in out or status is not None)    # the game is up, or it refused
        pump(settle)
        for key in keys:
            if status is not None:
                break
            try:
                if isinstance(key, int):
                    os.kill(pid, key)
                else:
                    for part in key if isinstance(key, tuple) else (key,):
                        os.write(master, part)
                        time.sleep(0.002)
            except OSError:
                break
            pump(0.15)
        pump(15, lambda: status is not None)
        stuck = status is None
        if stuck:
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
        try:
            restored = termios.tcgetattr(master) == before
        except termios.error:
            restored = None             # this system no longer answers once the program is gone
        os.close(master)
        text = out.decode(errors='replace').replace('\r', '')
        self.assertFalse(stuck, f'{cmd[-1]} did not stop; it printed {text[-300:]!r}')
        return status, text, restored

    def walk(self):
        exe, _ = self.script('walk', (
            'The board is 30 wide and 3 high. The column starts at 15. The score is a number.\n'
            'Every 200 milliseconds, the score goes up by 1.\n'
            'When the left key is pressed, the column decreases by 1.\n'
            'When the right key is pressed, the column increases by 1.\n'
            'Draw "@" at the column and 2. Show the score above the board.\n'), ['screen'])
        return [exe], [sys.executable, os.path.join(ROOT, 'intent'), 'run', os.path.join(self.dir, 'walk.intent')]

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_playing_in_a_terminal(self):
        import re
        for cmd in self.walk():
            with self.subTest(cmd[0]):
                status, out, restored = self.in_a_terminal(
                    cmd, [b'\x1b[D', b'\x1b[D', b'\x1b[C', b'\x1b[D', b'q'], settle=1.6)
                self.assertEqual((status, restored in (True, None)), (0, True))
                played, _, after = out.partition('\x1b[?1049l')         # its own screen, then back to the terminal
                self.assertTrue(played.startswith('\x1b[?1049h'))
                frames = [re.sub(r'\x1b\[[0-9?]*[A-Za-z]', '', f) for f in played.split('\x1b[H')[1:]]
                self.assertGreater(len(frames), 8)                  # time passed without any key
                self.assertTrue(frames[0].startswith('score 0\n+' + '-' * 30 + '+\n'))
                self.assertGreater(int(frames[-1].split('\n')[0].split()[1]), 5)    # the clock really ran
                player = [line.index('@') for line in frames[-1].split('\n') if '@' in line]
                self.assertEqual(player, [13])                      # from 15: two left, one right, one left
                self.assertEqual(after.strip('\n'), frames[-1].strip('\n'))         # the last board stays visible

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_the_terminal_always_comes_back(self):
        import signal
        for cmd in self.walk():
            for how, keys in [('Ctrl-C', [b'\x03']), ('Esc', [b'\x1b']), ('asked to stop', [signal.SIGTERM]),
                              ('hang-up', [signal.SIGHUP]), ('an arrow key in two parts, then q', [(b'\x1b', b'[D'), b'q'])]:
                with self.subTest(cmd[0] + ' ' + how):
                    status, out, restored = self.in_a_terminal(cmd, keys)
                    self.assertIn(restored, (True, None), 'the terminal was left changed')
                    self.assertEqual(status, 0)
                    self.assertIn('\x1b[?1049l', out)
                    if how.startswith('an arrow'):
                        self.assertEqual([line.index('@') for line in out.split('\x1b[?1049l')[1].split('\n')
                                          if '@' in line], [14])

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_a_terminal_too_small_is_refused(self):
        for cmd in self.walk():
            for rows, cols in [(5, 80), (30, 31)]:
                with self.subTest(f'{cmd[0]} {cols}x{rows}'):
                    status, out, restored = self.in_a_terminal(cmd, [], rows, cols)
                    self.assertEqual(out, f'this board needs a terminal at least 32 wide and 7 high; this one is '
                                          f'{cols} wide and {rows} high\n')
                    self.assertEqual((os.waitstatus_to_exitcode(status), restored in (True, None)), (1, True))
            status, out, _ = self.in_a_terminal(cmd, [b'q'], 7, 32)
            self.assertIn('\x1b[?1049h', out)                       # exactly big enough: it plays

    # ------------------------------------------------------------------ colour
    def draws(self, text, base=GAME):
        prog, diags, _ = understand('The board is 9 wide and 5 high.\n' + text, base)
        self.assertEqual([d.msg for d in diags], [], text)
        return [(d.glyph, d.colour) for d in prog.draws]

    def test_colour_phrasings(self):
        for text in ['Draw each rock at its x and y as a red "#".',
                     'Draw each rock at its x and y as "#" in red.',
                     'Draw each rock in red at its x and y as "#".',
                     'Draw a red "#" at the x and the y of each rock.',
                     'Paint every rock at its x and y with a red "#".']:
            self.assertEqual(self.draws(text), [('#', 'red')], text)
        self.assertEqual(self.draws('Draw a green "@" at the column and 2. Draw "*" at 1 and 1.'),
                         [('@', 'green'), ('*', None)])
        self.assertEqual(self.draws('Draw "@" in grey at the column and 2.'), [('@', 'grey')])
        level, where, d = problem('The board is 9 wide and 5 high. Draw each rock at its x and y as a red "#" in blue.',
                                  GAME)
        self.assertEqual((level, where, d.msg), ('error', 'in blue', 'one thing is drawn in one colour'))

    def test_a_colour_word_is_not_reserved(self):
        base = 'Paints is a collection. Each paint has a red (number) and a blue (number).\n'
        self.assertEqual(self.draws('Draw each paint at its red and blue as "#".', base), [('#', None)])

    COLOURED = ('The board is 9 wide and 3 high. The column starts at 4. The score is a number.\n'
                'Every 200 milliseconds, the score increases by 1.\n'
                'Draw a green "@" at the column and 2. Draw "*" at 6 and 2. Draw a red "#" at 7 and 2.\n')

    def test_colour_is_only_for_a_terminal(self):
        exe, out = self.script('ink', self.COLOURED, ['screen'])
        self.assertEqual(out, ['+---------+', '|         |', '|   @ *#  |', '|         |', '+---------+'])

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_colour_in_a_terminal(self):
        exe, _ = self.script('ink', self.COLOURED, ['screen'])
        for cmd in [exe], [sys.executable, os.path.join(ROOT, 'intent'), 'run', os.path.join(self.dir, 'ink.intent')]:
            with self.subTest(cmd[0]):
                status, out, _ = self.in_a_terminal(cmd, [b'q'])
                self.assertEqual(status, 0)
                played, _, after = out.partition('\x1b[?1049l')
                self.assertIn('|   \x1b[32m@\x1b[0m *\x1b[31m#\x1b[0m  |', played)
                self.assertIn('|   @ *#  |', after)            # what stays on the terminal is plain

    # ------------------------------------------------------------------ chance
    def test_chance_phrasings(self):
        for text in ['When space is pressed, the column becomes a random number between 1 and 30.',
                     'When space is pressed, set the column to a random number from 1 to 30.',
                     'When space is pressed, the column becomes a random whole number between one and 30.',
                     'When space is pressed, make the column a random value between 1 and 30.']:
            self.assertEqual(self.events(text), [(('key', 'space'), 'set column = random(1..30)')], text)
        self.assertEqual(self.events('Every second, the column increases by a random number between -1 and 1.'),
                         [(('every', 1000), 'set column = column + random(-1..1)')])

    def test_chance_that_cannot_be_read(self):
        for text, where, msg in [
                ('When space is pressed, the column becomes a random number.', 'random number',
                 'a random number between what and what?'),
                ('When space is pressed, the column becomes a random number up to 9.', 'random number',
                 'a random number between what and what?'),
                ('When space is pressed, the column becomes a random number between 9 and 2.', '9 and 2',
                 'the lower number has to come first')]:
            level, got, d = problem(text, GAME)
            self.assertEqual((level, got, d.msg), ('error', where, msg), text)
        for text in ['Whenever the score is over 5, the column becomes a random number between 1 and 9.',
                     'The board is 9 wide and 5 high. Draw "@" at a random number between 1 and 9 and 2.',
                     'Every second, remove the rocks whose x is a random number between 1 and 9.']:
            _, diags, _ = understand(text, GAME)
            self.assertEqual([d.msg for d in diags], ['chance cannot be used here'], text)

    def test_random_is_not_reserved(self):
        base = 'Draws is a collection. Each draw has a random (number) and a name.\n'
        self.assertEqual(meaning('Show the draws whose random is over 5.', base), 'list all of draw where random > 5')

    CHANCY = ('The board is 12 wide and 4 high. The column starts at 3. The score is a number. The lives start at 3.\n'
              'Rocks is a collection. Each rock has an x (number) and a y (number).\n'
              'Every 100 milliseconds, add a rock whose x is a random number between 1 and 12 and whose y is '
              'a random number from 1 to 4.\n'
              'Every 300 milliseconds, remove the rocks whose y is over 3.\n'
              'Every 100 milliseconds, if the score is over 2 and the lives are a random number between 1 and 3, '
              'the score becomes 0.\n'
              'Every 100 milliseconds, if the score is under 1 or the lives are a random number between 1 and 3, '
              'the score increases by 1.\n'
              'When space is pressed, the column becomes a random number between 1 and 12.\n'
              'The game is over when the score is over 6.\n'
              'Shuffle: set the column to a random number between 1 and 12.\n'
              'Draw each rock at its x and y as "#". Draw "@" at the column and 2. Show the score above the board.\n')

    def test_the_same_seed_draws_the_same_numbers(self):
        prog, diags, _ = understand('', self.CHANCY)
        self.assertEqual([d.msg for d in diags], [])
        cmds = ['wait 700', 'press space', 'screen']

        def run(seed):
            m = Machine(prog)
            return [o for c in [f'seed {seed}'] + cmds for o in m.run(c)]
        self.assertEqual(run(11), run(11))
        self.assertEqual(len({tuple(run(s)) for s in range(8)}), 8)        # and another seed, other numbers
        m = Machine(prog)
        self.assertEqual(m.run('seed x'), ['error: seed takes a number'])
        got = [m.draw(1, 6) for _ in range(600)]
        self.assertEqual(sorted(set(got)), [1, 2, 3, 4, 5, 6])              # both ends come up
        self.assertTrue(all(60 < got.count(k) < 140 for k in range(1, 7)))

    def test_chance_natively(self):
        for seed in range(4):
            rng = random.Random(seed)
            cmds = [f'seed {rng.randrange(-5, 10 ** 12)}']
            for _ in range(120):
                cmds.append(rng.choice(['wait 100', 'wait 250', 'press space', 'screen', 'score', 'restart', 'shuffle',
                                        f'seed {rng.randrange(99)}', 'seed', 'seed 1x']))
            self.script(f'chancy{seed}', self.CHANCY, cmds)

    def test_chance_is_replayed_from_the_journal(self):
        exe, _ = self.script('chancy', self.CHANCY, ['screen'])
        journal = os.path.join(self.dir, 'chancy.journal')

        def run(cmds):
            return subprocess.run([exe, journal], input='\n'.join(cmds) + '\n', capture_output=True, text=True,
                                  timeout=60).stdout
        first = run(['seed 5', 'wait 400', 'press space', 'restart', 'wait 300', 'press space', 'screen', 'score'])
        self.assertEqual(run(['screen', 'score']), first)       # chance, time, keys and the restart all came back
        with open(journal) as fh:
            self.assertEqual(fh.read().split('\n')[:4], ['seed 5', 'wait 400', 'press space', 'restart'])

    # ------------------------------------------------------------------ records that appear
    def test_records_that_appear(self):
        new = 'new rock: x = column, y = 1'
        for text, want in [
                ('Every second, add a rock whose x is the column and whose y is 1.', new),
                ('Every second, add a rock with x the column and y 1.', new),
                ('Every second, add a rock at x the column, y 1.', new),
                ('Every second, add a new rock whose x equals the column and whose y is 1.', new),
                ('Every second, add a rock whose y is 1 and whose x is the column.', 'new rock: y = 1, x = column'),
                ('Every second, if the score is over 3, add a rock whose x is the column and whose y is 1.',
                 new + ' where score > 3'),
                ('Every second, add a rock whose x is the column and whose y is 1 if the score is over 3.',
                 new + ' where score > 3'),
                ('Every second, if no rock has a y under 2, add a rock whose x is the column and whose y is 1.',
                 new + ' where no rock has y < 2')]:
            self.assertEqual(self.events(text), [(('every', 1000), want)], text)
        self.assertEqual(self.events('When space is pressed, add a rock whose x is the column plus 1 and whose y is 1.'),
                         [(('key', 'space'), 'new rock: x = column + 1, y = 1')])
        self.assertEqual(self.events('Every second, add 1 to the score.'), [(('every', 1000), 'set score = score + 1')])

    def test_a_record_that_appears_needs_every_property(self):
        level, where, d = problem('Every second, add a rock whose x is the column.', GAME)
        self.assertEqual((level, d.msg), ('question', 'what is the y of the new rock?'))
        level, where, d = problem('Every second, add a rock whose x is the y and whose y is 1.', GAME)
        self.assertEqual((level, d.msg), ('error', 'there is no "y" to read: the rock is not there yet'))
        level, where, d = problem('Every second, add a rock whose x is a given spot and whose y is 1.', GAME)
        self.assertEqual((level, d.msg), ('error', 'there is nobody to give the spot here'))
        level, where, d = problem('Every second, add a rock whose x is 1, whose y is 1 and whose x is 2.', GAME)
        self.assertEqual((level, where, d.msg), ('error', 'x', '"x" is given twice'))

    def test_records_that_appear_natively(self):
        for policy in ('Reject duplicates.', 'Replace duplicates.'):
            text = ('The tick is a number. The spot starts at 1.\n'
                    'Cars is a collection. Each car has a lane (number), a name and a made (number).\n'
                    f'Lanes are unique. {policy}\n'
                    'Every 100 milliseconds, the tick increases by 1.\n'
                    'Every 100 milliseconds, add a car whose lane is the spot, whose name is "auto" and whose made '
                    'is the tick.\n'
                    'Every 300 milliseconds, the spot becomes the spot plus 1 if the spot is under 4, otherwise 1.\n'
                    'When space is pressed, add a car whose lane is 9, whose name is "key" and whose made is the tick.\n'
                    'Every 700 milliseconds, remove the cars whose lane is 2.\n'
                    'Park: add a car. Fleet: show all cars. How many: count the cars. Find: find a car by lane.\n')
            rng = random.Random(policy)
            cmds = [rng.choice(['wait 100', 'wait 350', 'press space', 'fleet', 'how-many', 'find 9', 'find 2',
                                f'park {rng.randrange(1, 6)},hand,0']) for _ in range(200)]
            _, out = self.script('cars' + policy[:3], text, cmds)
            made = {line for line in out if line.startswith('9,key,')}
            self.assertEqual(len(made) == 1, policy.startswith('Rej'))      # kept as first made, or made again

    # ------------------------------------------------------------------ a hit that changes a value
    def test_conditions_about_other_records(self):
        hit = 'set lives = lives - 1 where any rock has (x == column and y == 5)'
        for text in ['Every second, if any rock has an x equal to the column and a y equal to 5, the lives decrease by 1.',
                     "Every second, if any rock's x is the column and its y is 5, the lives decrease by 1.",
                     'Every second, the lives decrease by 1 if any rock has an x equal to the column and a y equal to 5.',
                     "Every second, when a rock's x is the column and its y is 5, the lives decrease by 1.",
                     'Every second, if any rock has x = the column and y = 5 then decrease the lives by 1.']:
            self.assertEqual(self.events(text), [(('every', 1000), hit)], text)
        self.assertEqual(self.events('When space is pressed, if no rock has a y over 3, the score increases by 1.'),
                         [(('key', 'space'), 'set score = score + 1 where no rock has y > 3')])
        base = GAME + 'Shots is a collection. Each shot has a height (number).\n'
        self.assertEqual(self.events('Every second, if any rock has a y under 1, remove all shots.', base),
                         [(('every', 1000), 'remove shot where any rock has y < 1')])
        prog, diags, _ = understand('Whenever any rock has a y over 9, the lives become 0.', GAME)
        self.assertEqual(([d.msg for d in diags], [canon(r) for r in prog.rules]),
                         ([], ['set lives = 0 where any rock has y > 9']))

    def test_a_sentence_about_the_records_themselves_is_unchanged(self):
        self.assertEqual(self.events("Every second, if any rock's y is over 9, its y becomes 1."),
                         [(('every', 1000), 'update rock: y = 1 where y > 9')])
        level, where, d = problem('Every second, if any rock has a wobble over 3, the lives decrease by 1.', GAME)
        self.assertEqual((level, where, d.msg), ('error', 'wobble', 'I don\'t know the word "wobble"'))

    def test_conditions_about_other_records_natively(self):
        text = ('The board is 8 wide and 4 high. The column starts at 2. The lives start at 9. The score is a number.\n'
                'The alarm is text. The alarm starts at "calm".\n'
                'Rocks is a collection. Each rock has an x (number), a y (number) and a kind.\n'
                'Start with a rock at x 2, y 1, kind "stone". Start with a rock at x 5, y 3, kind "ice".\n'
                'Every 100 milliseconds, increase the y of every rock by 1.\n'
                "Every 100 milliseconds, if a rock's y is over 4, its y becomes 1.\n"
                'Every 100 milliseconds, if any rock has an x equal to the column and a y equal to 2, '
                'the lives decrease by 1.\n'
                'Every 100 milliseconds, if no rock has a y of 4, the score increases by 1.\n'
                'Whenever any rock has a kind of "ice" and a y under 2, the alarm becomes "cold".\n'
                'Whenever no rock has a y under 2, the alarm becomes "calm".\n'
                'When the right key is pressed, the column becomes 5 if the column is 2, otherwise 2.\n'
                'Melt: remove the rocks whose kind is a given kind. Drop: add a rock. Status: show the lives, the score '
                'and the alarm.\n'
                'Draw each rock at its x and y as "#". Draw "@" at the column and 2.\n')
        for seed in range(3):
            rng = random.Random(seed)
            cmds = [rng.choice(['wait 100', 'wait 100', 'wait 300', 'press right', 'status', 'screen', 'melt ice',
                                'melt stone', f'drop {rng.randrange(1, 9)},{rng.randrange(1, 5)},ice'])
                    for _ in range(150)]
            _, out = self.script(f'hits{seed}', text, cmds)
            self.assertTrue({'cold', 'calm'} <= {line.split(',')[-1] for line in out if line.count(',') == 2})

    # ------------------------------------------------------------------ several steps, restarting
    def test_several_steps_in_one_sentence(self):
        self.assertEqual(self.events('Every second, the score increases by 1 and then the column decreases by 2, '
                                     'and then remove the rocks whose y is over 9.'),
                         [(('every', 1000), 'set score = score + 1'), (('every', 1000), 'set column = column - 2'),
                          (('every', 1000), 'remove rock where y > 9')])
        self.assertEqual(self.events('When space is pressed, add a rock whose x is 1 and whose y is 1 and then '
                                     'the score increases by 1.'),
                         [(('key', 'space'), 'new rock: x = 1, y = 1'), (('key', 'space'), 'set score = score + 1')])
        level, where, d = problem('Every second, if the score is over 3, the score becomes 0 and then the lives '
                                  'decrease by 1.', GAME)
        self.assertEqual((level, where, d.msg), ('question', 'if the score is over 3, the score becomes 0',
                                                 'does this condition go with every step, or only the first?'))
        level, where, d = problem('Every second, the score increases by 1 and then.', GAME)
        self.assertEqual((level, d.msg), ('error', 'and then what?'))

    def test_restart(self):
        text = (GAME + 'Start with a rock at x 1, y 1.\n'
                'Every second, the lives decrease by 1. Every second, add a rock whose x is the lives and whose y is 2.\n'
                'The game is over when the lives are 0. Stones: show all rocks. Lives: show the lives.\n')
        self.assertEqual(self.run_ref(text, ['wait 1500', 'stones', 'wait 5000', 'wait 1', 'lives', 'restart', 'lives',
                                             'stones', 'wait 1500', 'lives', 'help']),
                         ['1,1', '2,2', 'the game is over', '0', '3', '1,1', '2',
                          'stones', 'lives', 'wait <milliseconds>', 'restart'])
        prog, _, _ = understand('Every second, the score increases by 1.', GAME)
        self.assertEqual(Machine(prog).run('restart'), ['error: unknown command restart'])     # nothing ends, so nothing restarts

    FALL = ('The board is 9 wide and 3 high. The lives start at 2. The column starts at 4.\n'
            'Every 100 milliseconds, the lives decrease by 1.\n'
            'The game is over when the lives are under 1.\n'
            'Draw a red "@" at the column and 2. Show the lives above the board.\n')

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_playing_again_after_the_game_is_over(self):
        hint = 'the game is over: enter plays again, q stops'
        exe, _ = self.script('fall', self.FALL, ['wait 100', 'screen', 'restart', 'screen'])
        for cmd in [exe], [sys.executable, os.path.join(ROOT, 'intent'), 'run', os.path.join(self.dir, 'fall.intent')]:
            with self.subTest(cmd[0]):
                # an arrow key and a stray letter are not answers; enter plays again; q stops
                status, out, restored = self.in_a_terminal(cmd, [b'\x1b[D', b'x', b'\r', b'x', b'q'], settle=0.6)
                self.assertEqual((status, restored in (True, None)), (0, True))
                played, _, after = out.partition('\x1b[?1049l')
                self.assertEqual(played.count(hint), 2)
                self.assertEqual(played.count('lives 2'), 2)                # it really began again
                self.assertEqual(after.strip('\n').split('\n')[-1], 'the game is over')
        status, out, _ = self.in_a_terminal([exe], [], 7, 80)               # no room for the last line
        self.assertEqual(out, 'this board needs a terminal at least 11 wide and 8 high; this one is 80 wide and 7 high\n')

    # ------------------------------------------------------------------ snake
    def snake(self):
        with open(os.path.join(ROOT, 'examples', 'snake.intent')) as fh:
            return fh.read()

    def test_snake_natively(self):
        for seed in range(4):
            rng = random.Random(seed)
            cmds = [f'seed {seed}']
            for _ in range(300):
                cmds.append(rng.choice(['wait 120'] * 6 + ['wait 360', 'press left', 'press right', 'press up',
                                                             'press down', 'screen', 'restart']))
            self.script(f'snake{seed}', self.snake(), cmds + ['screen'])

    def test_snake_eats_grows_and_dies(self):
        prog, diags, _ = understand('', self.snake())
        self.assertEqual([d.msg for d in diags], [])
        m = Machine(prog)
        state = m.data['(values)'][0]
        m.run('wait 1200')                              # ten steps to the right, onto the food
        self.assertEqual((state['column'], state['score'], state['length']), (20, 1, 5))
        self.assertNotEqual((state['food_x'], state['food_y']), (20, 7))
        m.run('wait 600')
        self.assertEqual(sorted(r['x'] for r in m.data['segment']), [21, 22, 23, 24])    # the body follows the head
        m.run('press left')                             # straight back is not a turn a snake can make
        self.assertEqual(state['sideways_speed'], 1)
        for key in ('down', 'left', 'up'):              # round in a tight circle, into its own body
            m.run(f'press {key}')
            m.run('wait 120')
        self.assertEqual(m.run('wait 120'), ['the game is over'])
        m.run('restart')
        self.assertEqual((state is m.data['(values)'][0], m.data['(values)'][0]['score'], m.data['segment']),
                         (False, 0, []))
        self.assertEqual(m.run('wait 2640'), [])        # 22 steps: off the right-hand edge
        self.assertEqual(m.run('wait 120'), ['the game is over'])

    @unittest.skipUnless(sys.platform != 'win32', 'needs a pseudo-terminal')
    def test_snake_in_a_terminal(self):
        exe, _ = self.script('snake', self.snake(), ['screen'])
        status, out, restored = self.in_a_terminal([exe], [b'\x1b[B', b'\x1b[D', b'q'], settle=0.5)
        self.assertEqual((status, restored in (True, None)), (0, True))
        played, _, after = out.partition('\x1b[?1049l')
        self.assertIn('\x1b[32mo', played)
        self.assertIn('\x1b[33m@', played)
        self.assertIn('\x1b[31m*', played)
        self.assertEqual(sum(line.count('o') for line in after.split('\n') if line.startswith('|')), 3)

    # ------------------------------------------------------------------ one record, found through the index
    CLUB = ('Players is a collection. Each player has a name (text), points (number) and a rank (text).\n'
            'Names are unique. Reject duplicates. Keep players in the order they were added.\n'
            'The bar starts at 100.\n'
            'Join: add a player. Leave: remove a player by name.\n'
            'Award: increase the points of the player with a given name by a given amount.\n'
            'Who: show the player with a given name.\n'
            'Rich: show the points of the players whose name is a given name and whose points are over the bar.\n'
            'Tally: count the players whose name is a given name.\n'
            'Best: show the top 2 players by points whose name is a given name.\n'
            'Gold: show the players whose rank is "gold".\n'
            'Raise-all: increase the points of every player by a given amount.\n'
            'Purge: remove the players whose points are under a given amount.\n')
    RANKS = ('Whenever a player\'s points are at least 100, their rank becomes "gold".\n'
             'Whenever a player\'s points are under 100, their rank becomes "plain".\n')

    def test_one_record_is_found_through_the_index(self):
        prog, diags, _ = understand('', self.CLUB + self.RANKS)
        self.assertEqual([d.msg for d in diags], [])
        plan = make_plan(prog)
        self.assertEqual({n: plan.tasks[n][0] for n in ('award', 'who', 'rich', 'tally', 'best', 'gold', 'raise-all')},
                         {'award': 'O(1) expected', 'who': 'O(1) expected', 'rich': 'O(1) expected',
                          'tally': 'O(1) expected', 'best': 'O(1) expected', 'gold': 'O(n)', 'raise-all': 'O(n)'})
        self.assertIn('one index probe on name, changed in place; then the rules look again at just that player',
                      plan.tasks['award'][1])
        self.assertIn('no rule has to look again', plan.tasks['leave'][1])
        self.assertIn('the 2 rules are applied until nothing changes', plan.tasks['raise-all'][1])
        why = [w for title, _, reasons in plan.colls['player'].decisions if title == 'index on name'
               for _, w in reasons]
        self.assertIn('"award" is about the one player with a certain name', why)
        slow = make_plan(prog, no_index=True)
        self.assertEqual((slow.tasks['award'][0], slow.picks), ('O(n)', {}))

    def test_rules_that_read_more_than_one_record_look_everywhere(self):
        for rule in ['Whenever a player\'s points are over the bar, their rank becomes "gold".\n',
                     'Whenever a player\'s points are under 0, remove them.\n']:
            prog, diags, _ = understand('', self.CLUB + rule)
            self.assertEqual([d.msg for d in diags], [], rule)
            plan = make_plan(prog)
            self.assertFalse(plan.local_rules)
            self.assertIn('the 1 rule is applied until nothing changes', plan.tasks['award'][1])

    def test_one_record_natively(self):
        names = ['ann', 'bob', 'cy', 'dee', 'eve', 'flo']
        programs = {
            'ranks': self.CLUB + self.RANKS,
            # rules that never come to rest: every command must still say so, exactly as the meaning does
            'restless': self.CLUB + ('Whenever a player\'s points are at least 100, their points become 50.\n'
                                     'Whenever a player\'s points are under 100 and their points are over 40, '
                                     'their points become 150.\n'),
            'bar': self.CLUB + 'Whenever a player\'s points are over the bar, their rank becomes "gold".\n'
                               'Raise: set the bar to a given bar.\n',
            'replace': (self.CLUB + self.RANKS).replace('Reject', 'Replace'),
            'norules': self.CLUB}
        for name, text in programs.items():
            with self.subTest(name):
                rng = random.Random(name)
                cmds = []
                for _ in range(400):
                    who = rng.choice(names)
                    cmds.append(rng.choice([
                        f'join {who},{rng.randrange(0, 160)},new', f'award {rng.randrange(-60, 90)},{who}',
                        f'award {rng.randrange(-60, 90)},{who}', f'who {who}', f'rich {who}', f'tally {who}',
                        f'best {who}', 'gold', f'leave {who}', f'raise-all {rng.randrange(-20, 20)}',
                        f'purge {rng.randrange(0, 30)}'] + ([f'raise {rng.randrange(50, 150)}'] if name == 'bar' else [])))
                _, out = self.script('club-' + name, text, cmds)
                if name == 'restless':
                    self.assertIn('error: the rules keep changing each other', out)
                if name == 'ranks':
                    self.assertTrue(any(line.endswith(',gold') for line in out))

    def test_one_record_among_many_is_quick(self):
        import time
        exe, _ = self.script('club-many', self.CLUB + self.RANKS, ['gold'])
        n = 20000
        cmds = [f'join p{i},0,new' for i in range(n)] + [f'award 7,p{(i * 7919) % n}' for i in range(40000)] + \
            ['who p5', 'tally p6']
        start = time.time()
        got = subprocess.run([exe], input='\n'.join(cmds) + '\n', capture_output=True, text=True, timeout=120)
        self.assertEqual(got.stdout, 'p5,14,plain\n1\n')
        self.assertLess(time.time() - start, 20)        # a pass over every player for every award took over a minute

    def test_plurals_that_end_in_us(self):
        from intentc.lexicon import singular
        self.assertEqual([singular(w) for w in ['menus', 'skus', 'gurus', 'status', 'bonus', 'virus', 'campus',
                                                'us', 'bus', 'famous', 'customers', 'addresses']],
                         ['menu', 'sku', 'guru', 'status', 'bonus', 'virus', 'campus', 'us', 'bus', 'famous',
                          'customer', 'address'])
        base = ('Skus is a collection. Each sku has a code (text), a stock (number) and a status (text).\n'
                'Menus is a collection. Each menu has a title (text) and a bonus (number).\n')
        self.assertEqual(meaning('Show the skus whose stock is under 5 and whose status is "live".', base),
                         'list all of sku where stock < 5 and status == "live"')
        self.assertEqual(meaning('Show the menus whose bonus is over 2.', base), 'list all of menu where bonus > 2')


FIELD = ('The board is 12 wide and 8 high.\n'
         'The hurt starts at 0. The clear starts at 0. The gap starts at 0.\n'
         'Shots have an x (number) and a y (number).\n'
         'Aliens have an x (number), a y (number) and a hit (number).\n'
         'Cells have an x (number) and a y (number).\n'
         'Bombs have an x (number) and a y (number).\n')

BATTLE = FIELD + '''The fill1 starts at 0. The fill2 starts at 0.
At the start there is an alien whose x is 3, whose y is 2 and whose hit is 0.
At the start there is an alien whose x is 5, whose y is 2 and whose hit is 0.
At the start there is an alien whose x is 7, whose y is 4 and whose hit is 0.
At the start there is a cell whose x is 1 and whose y is 8.
At the start there is a cell whose x is 2 and whose y is 8.
At the start there is a cell whose x is 3 and whose y is 8.
At the start there is a cell whose x is 3 and whose y is 7.
At the start there is a cell whose x is 3 and whose y is 6.
Draw each alien as a green "A" at its x and y.
Draw each shot as a yellow "|" at its x and y.
Draw each cell as a blue "#" at its x and y.
When space is pressed, add a shot whose x is 3 and whose y is 8.
When a is pressed, add a shot whose x is 7 and whose y is 6 if the number of shots is under 3.
When b is pressed, add a cell whose x is the number of cells plus 1 and whose y is 5.
Every 100 milliseconds, decrease the y of the shots by 1.
Every 100 milliseconds, set the hit of the aliens to 1 if any shot has an x equal to the alien's x and a y equal to its y.
Every 100 milliseconds, remove the shots that have the same x and y as an alien.
Every 100 milliseconds, if the hurt is 0, remove the aliens whose hit is 1.
Every 100 milliseconds, remove the shots whose y is under 1.
Every 100 milliseconds, set the fill1 to the number of cells whose y is 8.
Every 100 milliseconds, set the fill2 to the total of the x of the cells.
Every 100 milliseconds, set the gap to the largest y of the cells where the number of cells with the same y is 3.
When d is pressed, remove the cells if the number of cells with the same y is 3.
When e is pressed, increase the y of the cells whose y is under the gap by 1 if the gap is over 0.
When f is pressed, increase the x of the cells by 1 if the number of cells with the same y is over 1.
When g is pressed, remove the cells whose x is the x of any alien.
Show the fill1, the fill2 and the gap above the board.
The game is over when the number of aliens is 0.
'''


class TestAcross(TestNativeAgainstReference):
    script = TestLive.script

    def events(self, text, base=FIELD):
        prog, diags, _ = understand(text, base)
        self.assertEqual([d.msg for d in diags], [], text)
        return [canon(t) for t in prog.events]

    def test_a_condition_in_front_and_one_behind(self):
        for a, b in [('Every second, if the hurt is 1, remove the bombs whose y is at least 7.',
                      'Every second, remove the bombs whose y is at least 7 if the hurt is 1.'),
                     ('Every second, increase the y of the cells whose y is under 1 by 1 if the clear is 1.',
                      "Every second, increase each cell's y by 1 if its y is under 1 and the clear is 1."),
                     ('Every second, if the clear is 1, increase the y of the cells whose y is under 1 by 1.',
                      'Every second, increase the y of the cells whose y is under 1 by 1 if the clear is 1.')]:
            with self.subTest(a):
                first, second = self.events(a)[0], self.events(b)[0]
                self.assertEqual(first.split(' where ')[0], second.split(' where ')[0])
                self.assertEqual(sorted(first.split(' where ')[1].split(' and ')),
                                 sorted(second.split(' where ')[1].split(' and ')))

    def test_names_with_a_number_in_them(self):
        prog, diags, _ = understand('The fill1 starts at 0.\nThe fill2 starts at 0.\nThe fill10 starts at 3.\n'
                                    'Every second, increase the fill2 by the fill1.', FIELD)
        self.assertEqual(diags, [])
        self.assertEqual(canon(prog.events[0]), 'set fill2 = fill2 + fill1')
        # hurt already starts at 0, so this cannot be a slip for it (it would start twice): it is a new value,
        # and since nothing uses it, a note points at it
        prog, diags, p = parse(FIELD + 'The hurtt starts at 5.')
        diags += check(prog, p.src)
        self.assertEqual([d.level for d in diags if d.level != 'note'], [])
        self.assertEqual(prog.collections['(values)'].fields['hurt'].init, 0)
        self.assertIn('"hurtt" is never used', [d.msg for d in diags])

    def test_counting_phrasings(self):
        for text in ['Every second, set the clear to 1 if the number of cells whose y is 3 is 8.',
                     'Every second, set the clear to 1 if the count of cells whose y is 3 is 8.',
                     'Every second, set the clear to 1 if the number of cells with a y of 3 is 8.',
                     'Every second, if the number of cells whose y is 3 is 8, set the clear to 1.',
                     'Every second, the clear becomes 1 if the count of cells where the y is 3 equals 8.']:
            with self.subTest(text):
                self.assertEqual(self.events(text), ['set clear = 1 where count(cells where y == 3) == 8'])
        self.assertEqual(self.events('Every second, set the gap to the number of cells.'), ['set gap = count(cells)'])
        self.assertEqual(self.events('Every second, set the gap to the total of the x of the cells whose y is over 2.'),
                         ['set gap = sum(x of cells where y > 2)'])
        self.assertEqual(self.events('Every second, set the gap to the largest y of the cells.'),
                         ['set gap = max(y of cells)'])
        self.assertEqual(self.events('Every second, increase the hurt by the number of aliens whose hit is 1.'),
                         ['set hurt = hurt + count(aliens where hit == 1)'])
        self.assertEqual(self.events('Every second, remove the cells if the number of cells with the same y is 8.'),
                         ['remove cell where count(cells where y == its y) == 8'])
        self.assertEqual(self.events('Every second, set the gap to the largest y of the cells where the number of '
                                     'cells with the same y is 10.'),
                         ['set gap = max(y of cells where count(cells where y == its y) == 10)'])
        self.assertEqual(self.events('When space is pressed, add a shot whose x is 1 and whose y is 1 if the number '
                                     'of shots is under 3.'), ['new shot: x = 1, y = 1 where count(shots) < 3'])
        prog, diags, _ = understand('The game is over when the number of aliens is 0.', FIELD)
        self.assertEqual(diags, [])
        self.assertEqual(fmt_cond(prog.ends[0].where), 'count(aliens) == 0')
        # asking for a count is still a command, and a ranking is still a ranking
        self.assertEqual(meaning('How many cells have a y of 3?', FIELD), 'count() of cell where y == 3')
        self.assertEqual(meaning('Show the cell with the largest y.', FIELD),
                         'list all of cell sorted by y descending, first 1')

    def test_matching_phrasings(self):
        both = 'remove alien where any shot has (x == its x and y == its y)'
        for text in ["Every second, remove the aliens if any shot has an x equal to an alien's x and a y equal to its y.",
                     'Every second, remove the aliens if any shot has an x equal to its x and a y equal to its y.',
                     'Every second, remove the aliens that have the same x and y as a shot.',
                     'Every second, remove each alien that is at the same x and y as a shot.',
                     'Every second, remove the aliens if any shot has the same x and y.',
                     'Every second, if any shot has the same x and y as the alien, remove the aliens.']:
            with self.subTest(text):
                self.assertEqual(self.events(text), [both])
        self.assertEqual(self.events('Every second, remove the aliens whose x is the x of any shot.'),
                         ['remove alien where any shot has x == its x'])
        self.assertEqual(self.events('Every second, remove the bombs that do not have the same x as an alien.'),
                         ['remove bomb where no alien has x == its x'])
        self.assertEqual(self.events('Every second, decrease the y of the aliens whose y is over the y of any bomb by 1.'),
                         ['update alien: y = y - 1 where any bomb has y < its y'])
        self.assertEqual(self.events('Every second, set the hit of the aliens to 1 if any shot has the same x and y.'),
                         ['update alien: hit = 1 where any shot has (x == its x and y == its y)'])
        self.assertEqual(self.events('Every second, if the hurt is 1 and no bomb has a y over 3, set the clear to 2.'),
                         ['set clear = 2 where (no bomb has y > 3) and hurt == 1'])
        # a sentence that is about those very records keeps its old meaning
        self.assertEqual(self.events('Every second, remove the bombs if any bomb has a y over 7.'),
                         ['remove bomb where y > 7'])

    def test_what_is_asked_about_other_records(self):
        for text, msg in [('Every second, set the hurt to 1 if any shot has an x equal to its y.', 'whose y is this?'),
                          ("Every second, remove the aliens if any shot has an x equal to the bomb's x.",
                           'this sentence is about Aliens, not about a bomb'),
                          ('Every second, remove the aliens if any shot has the same hit.',
                           'Shots has no property "hit"'),
                          ('Every second, set the y of the cells to the number of cells whose y is over its y.',
                           'this works out the new "y" from the "y" of the other cells while changing them'),
                          ('When space is pressed, add a shot whose x is 1 and whose y is 1 if any alien has an x '
                           'equal to its y.', 'whose y is this?'),
                          ('Every second, set the hurt to the number of cells whose colour is 3.',
                           'I don\'t know the word "colour"')]:
            with self.subTest(text):
                _, diags, _ = understand(text, FIELD)
                self.assertEqual([d.msg for d in diags], [msg])
        # the same value may be read from the other records as long as it is not the one being changed
        self.assertEqual(self.events('Every second, set the y of the cells to the number of cells whose x is over its x.'),
                         ['update cell: y = count(cells where x > its x)'])

    def test_the_plan_says_what_looking_costs(self):
        prog, diags, p = understand('', BATTLE)
        self.assertEqual(diags, [])
        plan = make_plan(prog)
        hit = next(t for t in prog.events if 'hit = 1' in canon(t))
        self.assertEqual(plan.tasks[hit.name][0], 'O(n x m)')
        self.assertIn('for each one, a pass over the shots', plan.tasks[hit.name][1])
        fill = next(t for t in prog.events if canon(t).startswith('set fill1'))
        self.assertEqual(plan.tasks[fill.name][0], 'O(1)')
        self.assertIn('a pass over the cells', plan.tasks[fill.name][1])

    def test_counting_and_matching_natively(self):
        for seed in range(5):
            rng = random.Random(seed)
            cmds = []
            for _ in range(250):
                cmds.append(rng.choice(['wait 100'] * 5 + ['press space', 'press a', 'press b', 'press b', 'press d',
                                                           'press e', 'press f', 'press g', 'screen', 'picture',
                                                           'wait 300', 'restart']))
            self.script(f'battle{seed}', BATTLE, cmds + ['screen'])

    def test_which_records_change_is_decided_first(self):
        # the native program keeps records in another order after a removal; the answer must not depend on it
        text = ('Stones is a collection. Each stone has a name (text), a row (number) and a mark (number).\n'
                'Names are unique. Reject duplicates.\n'
                'Put: add a stone.\nDrop: remove a stone by name.\nRoll: show the stones sorted by name.\n'
                'Clear: remove the stones if the number of stones with the same row is 3.\n'
                'Tag: set the mark of the stones to 1 if the number of stones whose mark is 0 is over 2.\n'
                'Pairs: increase the mark of the stones by 10 if the number of stones with the same row is over 1.\n'
                'Crowd: show the number of stones.\n')
        cmds = [f'put s{i},{i % 4},0' for i in range(14)] + ['drop s1', 'drop s6', 'roll', 'tag', 'roll', 'pairs', 'roll',
                                                             'clear', 'roll', 'drop s0', 'put s20,2,0', 'put s21,2,0',
                                                             'clear', 'roll', 'tag', 'pairs', 'roll', 'crowd']
        self.script('stones', text, cmds)
        prog, _, _ = understand('', text)
        m = Machine(prog)
        for c in ['put a,1,0', 'put b,1,0', 'put c,1,0', 'put d,2,0', 'clear']:
            m.run(c)
        self.assertEqual(m.run('roll'), ['d,2,0'])               # all three went: none saw the others already gone
        for c in ['put e,2,0', 'put f,2,0', 'tag']:
            m.run(c)
        self.assertEqual(m.run('roll'), ['d,2,1', 'e,2,1', 'f,2,1'])     # the third was tagged too

    def test_a_game_with_no_single_values(self):
        text = ('The board is 6 wide and 3 tall.\nAliens have an x (number) and a y (number).\n'
                'At the start there is an alien whose x is 2 and whose y is 2.\n'
                'Draw each alien as "A" at its x and y.\n'
                'When space is pressed, remove the aliens whose x is 2.\n'
                'The game is over when the number of aliens is 0.\n')
        _, out = self.script('novalues', text, ['screen', 'press space', 'picture', 'press space', 'restart', 'picture'])
        self.assertEqual(out[5:15], ['+------+', '|      |', '|      |', '|      |', '+------+', '~',
                                     '......', '......', '......', 'the game is over'])
        self.assertEqual(out[15], 'the game is over')
        self.assertEqual(out[-4:], ['~', '......', '......', '......'])

    def shooter(self):
        with open(os.path.join(ROOT, 'examples', 'shooter.intent')) as fh:
            return fh.read()

    def test_shooter_natively(self):
        for seed in range(3):
            rng = random.Random(seed)
            cmds = ['screen']
            for _ in range(500):
                cmds.append(rng.choice(['press space'] * 3 + ['press left'] * 2 + ['press right'] * 2 +
                                       ['wait 60', 'wait 120', 'wait 400', 'wait 37', 'picture']))
            self.script(f'shooter{seed}', self.shooter(), cmds + ['screen'])

    def test_shooter_can_be_won(self):
        prog, diags, _ = understand('', self.shooter())
        self.assertEqual(diags, [])
        m = Machine(prog)
        for _ in range(2000):                   # stand under the lowest alien there is and keep firing
            if m.over():
                break
            target = max(m.data['alien'], key=lambda a: a['y'])
            col = m.data['(values)'][0]['column']
            m.run('press left' if target['x'] < col else 'press right' if target['x'] > col else 'press space')
            m.run('wait 60')
        self.assertTrue(m.over())
        self.assertEqual(m.data['alien'], [])
        self.assertEqual(m.data['(values)'][0]['score'], 9)

    def test_picture(self):
        _, out = self.script('pic', BATTLE, ['press space', 'wait 400', 'picture'])
        cut = out.index('~')
        self.assertEqual(out[cut - 10], '+------------+')
        self.assertEqual(out[cut + 2], '..g.g.......')      # the aliens, in green
        self.assertEqual(out[cut + 4], '..y...g.....')      # the shot on its way up, and the third alien
        self.assertEqual(out[cut + 7], '..b.........')
        self.assertEqual(out[cut + 8], 'bbb.........')
        self.assertEqual(len(out) - cut, 9)                 # nothing after the colours: the game goes on


class TestNetwork(TestNativeAgainstReference):
    """A served program takes the commands it takes on stdin, and answers each caller."""
    script = TestLive.script

    def port(self):
        import socket
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def serving(self, argv):
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=ROOT)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        self.assertIn('serving on port', p.stdout.readline())
        return p

    def raw(self, port, text):
        import socket
        with socket.create_connection(('127.0.0.1', port), timeout=10) as s:
            s.sendall(text.encode())
            s.shutdown(socket.SHUT_WR)
            out = b''
            while True:
                got = s.recv(65536)
                if not got:
                    return out.decode()
                out += got

    def get(self, port, path):
        import urllib.request
        return urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10).read().decode()

    def post(self, port, body):
        import urllib.request
        req = urllib.request.Request(f'http://127.0.0.1:{port}/', data=body.encode())
        return urllib.request.urlopen(req, timeout=10).read().decode()

    def customers(self):
        src, exe = os.path.join(ROOT, 'examples', 'customers.intent'), os.path.join(self.dir, 'netcustomers')
        self.assertIsNotNone(build(src, exe, quiet=True))
        return src, exe

    def talk(self, port):
        """One conversation, the same for either server."""
        said = [self.post(port, 'add ann,30,a@x\nadd bob,17,b@x\nlist\ncount\n'),
                self.get(port, '/find-by-email/a%40x'),
                self.get(port, '/count'),
                self.raw(port, 'add cy,40,c@x\nadults\ncount\nnonsense\n'),
                self.get(port, '/list-by-age'),
                self.post(port, 'remove-by-email b@x\ncount')]
        page = self.get(port, '/')
        self.assertTrue(page.startswith('<!doctype html>'))
        self.assertIn('find-by-email &lt;email>', page)
        return said

    def test_the_same_answers_from_both_servers(self):
        src, exe = self.customers()
        port = self.port()
        self.serving([exe, 'serve', str(port)])
        native = self.talk(port)
        port = self.port()
        self.serving([sys.executable, '-m', 'intentc.cli', 'serve', src, '--port', str(port)])
        self.assertEqual(self.talk(port), native)
        self.assertEqual(native, ['ann,30,a@x\nbob,17,b@x\n2\n', 'ann,30,a@x\n', '2\n',
                                  'ann\ncy\n3\nerror: unknown command nonsense\n',
                                  'cy,40,c@x\nann,30,a@x\nbob,17,b@x\n', '2\n'])

    def test_many_callers_at_once(self):
        import socket
        _, exe = self.customers()
        port = self.port()
        self.serving([exe, 'serve', str(port)])
        conns = [socket.create_connection(('127.0.0.1', port), timeout=10) for _ in range(20)]
        for i, c in enumerate(conns):               # half a command each, then the rest: nobody waits for anybody
            c.sendall(f'add p{i},{20 + i}'.encode())
        for i, c in enumerate(conns):
            c.sendall(f',p{i}@x\ncount\n'.encode())
        counts = sorted(int(c.makefile().readline()) for c in conns)
        self.assertEqual(counts, list(range(1, 21)))
        long = ''.join(f'find-by-email p{i % 20}@x\n' for i in range(3000))     # far more than arrives in one piece
        self.assertEqual(self.raw(port, long), ''.join(f'p{i % 20},{20 + i % 20},p{i % 20}@x\n' for i in range(3000)))
        for c in conns:
            c.close()

    def test_a_served_program_remembers(self):
        _, exe = self.customers()
        journal = os.path.join(self.dir, 'net.journal')
        port = self.port()
        p = self.serving([exe, 'serve', str(port), journal])
        self.post(port, 'add ann,30,a@x\nadd bob,17,b@x\ncount\n')
        self.get(port, '/double-age')
        p.kill()
        p.wait()
        with open(journal) as fh:
            self.assertEqual(fh.read(), 'add ann,30,a@x\nadd bob,17,b@x\ndouble-age\n')
        port = self.port()
        self.serving([exe, 'serve', str(port), journal])
        self.assertEqual(self.get(port, '/list'), 'ann,60,a@x\nbob,34,b@x\n')

    def test_serving_needs_a_port(self):
        _, exe = self.customers()
        got = subprocess.run([exe, 'serve'], capture_output=True, text=True, timeout=10)
        self.assertEqual((got.returncode, got.stdout), (1, 'error: serve needs a port, e.g. "serve 8080"\n'))
        port = self.port()
        self.serving([exe, 'serve', str(port)])
        got = subprocess.run([exe, 'serve', str(port)], capture_output=True, text=True, timeout=10)
        self.assertEqual((got.returncode, got.stdout), (1, f'error: cannot listen on port {port}\n'))

    def test_a_served_game_lives_in_real_time(self):
        import time
        src, exe = os.path.join(ROOT, 'examples', 'snake.intent'), os.path.join(self.dir, 'netsnake')
        self.assertIsNotNone(build(src, exe, quiet=True))
        for argv in ([exe, 'serve'], [sys.executable, '-m', 'intentc.cli', 'serve', src, '--port']):
            with self.subTest(argv[0]):
                port = self.port()
                self.serving(argv + [str(port)])
                page = self.get(port, '/')
                self.assertIn('<canvas', page)
                self.assertIn('"board": [30, 14]', page)
                self.assertIn('"keys": ["left", "right", "up", "down"]', page)
                first = self.get(port, '/picture')
                self.assertEqual(first.split('\n')[17], '~')
                self.post(port, 'press down\n')
                time.sleep(0.6)
                later = self.get(port, '/picture')
                self.assertNotEqual(first, later)               # nobody sent "wait": the clock did
                head = lambda pic: next(y for y, row in enumerate(pic.split('\n')) if '@' in row)  # noqa: E731
                self.assertGreater(head(later), head(first))            # and it went the way the key said
                self.assertIn('y', later.split('~')[1])         # the head is yellow in the picture

    def test_the_page_comes_from_the_program(self):
        from intentc.web import from_path, page, title_of
        prog, _, _ = understand('', BATTLE)
        html = page(prog, title_of('games/space-battle.intent'))
        self.assertIn('<title>space battle</title>', html)
        self.assertIn('"board": [12, 8]', html)
        self.assertIn('"restart": true', html)
        prog, _, _ = understand('Find a customer by email.\n')
        self.assertIn('"board": null', page(prog, 'x'))
        self.assertEqual(from_path('/find-by-name/ann%20lee?x=1'), 'find-by-name ann lee')
        self.assertEqual(from_path('/count'), 'count')


MATHS = (
    'Sin: take an angle and return the sine of angle.\n'
    'Cos: take an angle and return the cosine of angle.\n'
    'Root: take n and return the square root of n if n is at least 0, otherwise 0.\n'
    'Hyp: take a and b and return the square root of (a times a plus b times b).\n'
    'Wave: take a turn and return 12 times the sine of turn plus 3.\n'
    'Price root: take a price and return the square root of price if price is at least 0.00, otherwise 0.00.\n'
    'Size: take n and return the absolute value of n.\n'
    'Near: take an angle and return the nearest whole number to (12 times the sine of angle).\n'
    'Part: take an angle and return the whole part of (12 times the cosine of angle).\n'
    'Half: take a price and return the nearest whole number to (price plus 0.00).\n'
)


class TestMaths(unittest.TestCase):
    """Square roots, sines and cosines, worked out in whole numbers so every machine gives the same digits."""
    setUpClass = classmethod(TestNativeAgainstReference.setUpClass.__func__)
    tearDownClass = classmethod(TestNativeAgainstReference.tearDownClass.__func__)
    script = TestLive.script

    def test_values(self):
        from intentc.ir import droot, root, sine
        self.assertEqual([sine(a * 100) for a in (0, 30, 90, 150, 180, 210, 270, 360, -30, 720 + 45)],
                         [0, 50, 100, 50, 0, -50, -100, 0, -50, 71])
        self.assertEqual(sine(4550), 71)            # 45.5 degrees: 0.713... between the table's whole degrees
        self.assertEqual([root(n) for n in (0, 1, 8, 9, 10, 10 ** 18, -4)], [0, 1, 2, 3, 3, 10 ** 9, 0])
        self.assertEqual([droot(n) for n in (225, 200, 100, 1, 0)], [150, 141, 100, 10, 0])

    def test_native_matches_reference(self):
        rng = random.Random(7)
        cmds = []
        for _ in range(400):
            a = rng.choice([rng.randint(-1000, 1000), rng.randint(-10 ** 9, 10 ** 9), rng.randint(0, 90)])
            cmds += [f'sin {a}', f'cos {a}', f'root {abs(a) * rng.choice([1, 7919, 10 ** 6])}',
                     f'hyp {rng.randint(-3000, 3000)},{rng.randint(-3000, 3000)}', f'wave {a}',
                     f'price-root {rng.randint(0, 10 ** 6)}.{rng.randint(0, 99):02d}', f'size {a}', f'near {a}',
                     f'part {a}', f'half {rng.randint(-999, 999)}.{rng.choice([0, 49, 50, 51, 99]):02d}']
        _, out = self.script('maths', MATHS, cmds + ['sin 9223372036854775807', 'cos -9223372036854775807',
                                                     'root 9223372036854775807', 'size -9223372036854775807',
                                                     'half 2.50', 'half -2.50', 'near 30', 'part 210'])
        self.assertEqual(out[-4:], ['3', '-3', '6', '-10'])     # halves away from zero; the whole part toward it

    def test_a_root_of_something_that_can_be_negative_is_a_question(self):
        level, _, d = problem('Bad: take n and return the square root of n.\n', '')
        self.assertEqual((level, d.msg), ('question', 'what should happen when the given n is below 0?'))
        self.assertIn('"the square root of n if n is at least 0, otherwise 0"', d.hint)
        for ok in ['Ok: take n and return the square root of (n times n).\n',
                   'Ok: take n and return the square root of n if n is over 5, otherwise 1.\n',
                   'Ok: take n and return 0 if n is under 0, otherwise the square root of n.\n']:
            with self.subTest(ok):
                self.assertEqual(understand(ok, '')[1], [])

    def test_the_sine_of_text_is_an_error(self):
        level, _, d = problem('Bad: take a name (text) and return the sine of name.\n', '')
        self.assertEqual(level, 'error')


class TestCrowdedNames(unittest.TestCase):
    """Programs with many short names, like the trig values of a 3D scene: no name may silently become another."""

    def values(self, text):
        prog, diags, _ = understand(text, '')
        return diags, {f.name: f.init for f in prog.collections[STATE].fields.values()}

    def test_near_names_that_each_start_are_separate_values(self):
        self.assertEqual(self.values('The cosy starts at 1000. The cosp starts at 900. The cosr starts at 800.'),
                         ([], {'cosy': 1000, 'cosp': 900, 'cosr': 800}))

    def test_a_slip_still_gives_a_declared_value_its_start(self):
        self.assertEqual(self.values('The score is a number. The scroe starts at 5.'), ([], {'score': 5}))

    def test_a_value_starts_once(self):
        level, _, d = problem('The score starts at 1.\nThe score starts at 2.\n', '')
        self.assertEqual((level, d.msg, d.line), ('error', '"score" already starts at 1', 2))

    def test_a_property_cannot_take_a_single_values_name(self):
        level, where, d = problem('The sy starts at 500.\nPoints is a collection.\n'
                                  'Each point has an x (number).\nEach point has an sy (number).\n', '')
        self.assertEqual((level, where, d.msg), ('error', 'sy', '"sy" is already a single value'))

    def test_whole_number_division_is_noted_once(self):
        prog, diags, p = parse(BASE + 'Halve: set the age to the age divided by 2.\n'
                                      'Third: set the salary to the salary divided by 3.\n')
        notes = [d for d in diags + check(prog, p.src) if 'drops the remainder' in d.msg]
        self.assertEqual(len(notes), 1)


if __name__ == '__main__':
    unittest.main()
