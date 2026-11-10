"""The knowledge system: every word or phrase Intent understands, and what concept it maps to.

Three classes of word exist in an Intent program:
  1. concepts listed here (many phrasings -> one concept),
  2. filler listed here (carries no computational meaning, safe to drop),
  3. names the program itself declared (collections, properties, parameters).
Anything else is reported to the programmer. Nothing unknown is ever dropped.
"""

PHRASES = {}


def _add(kind, val, phrases):
    for ph in phrases.split('|'):
        ph = ph.strip()
        if ph:
            PHRASES[tuple(ph.split())] = [(kind, val)]


# ---- filler: no computational meaning -------------------------------------------------
_add('FILLER', None, '''the|a|an|please|so|basically|just|really|simply|actually|well|okay|ok
 |i want to|i want|i would like to|i'd like to|i need to|we need to|we want to|i wish to
 |what i really want is to|what i want is to|i have|we have|there is|there are|are there|is there
 |let me|let us|can you|could you|it will|should be able to|be able to|able to
 |that|which|also|now|new|there|will|shall|can|do|does|some|should|must|be|me
 |of|in|for|across|among|within|on
 |their|his|her|its|our|my|your|own
 |called|named|function|create a function|write a function|define a function|create|define
 |value of|a value of|the value of|value|values
 |as large|as big|as much|as high|as great|as many
 |whole|entire|preserve|remember|maintain|always|kept|stay|stays
 |requirements|operations|capabilities|required behaviour|required behavior|rules''')

# ---- numbers --------------------------------------------------------------------------
for _i, _w in enumerate('''zero one two three four five six seven eight nine ten eleven twelve
 thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'''.split()):
    _add('NUM', _i, _w)
_add('NUM', 100, 'hundred|a hundred|one hundred')
_add('NUM', 1000, 'thousand|a thousand|one thousand')
PHRASES[('twice',)] = [('NUM', 2), ('OP', 'mul')]
PHRASES[('thrice',)] = [('NUM', 3), ('OP', 'mul')]

# ---- arithmetic -----------------------------------------------------------------------
_add('OP', 'mul', 'multiplied by|times|multiplied with')
_add('OP', 'add', 'plus|added to')
_add('OP', 'sub', 'minus')
_add('OP', 'div', 'divided by')
_add('OP', 'rem', 'modulo|mod')
_add('FN', 'sqrt', 'square root of|root of')
_add('FN', 'sin', 'sine of|sin of')
_add('FN', 'cos', 'cosine of|cos of')
_add('FN', 'abs', 'absolute value of')
_add('FN', 'round', 'nearest whole number to|rounded value of')
_add('FN', 'trunc', 'whole part of')
_add('PARITY', 0, 'even')
_add('PARITY', 1, 'odd')

_add('VERB', 'multiply', 'multiply|multiplying|multiplies')
_add('VERB', 'divide', 'divide|dividing|divides')
_add('VERB', 'increase', 'increase|increasing|increases|increased|raise|raising|raised|increment|bump|bump up|boost|grow|grows|goes up|go up|rises|rise')
_add('VERB', 'decrease', 'decrease|decreasing|decreases|decreased|reduce|reducing|reduced|lower|lowering|lowered|decrement|shrink|shrinks|cut|cut down|goes down|go down|falls|fall')
_add('VERB', 'addv', 'add|adding|adds')
_add('VERB', 'subv', 'subtract|subtracting|subtracts|take away')
_add('VERB', 'set', 'set|setting|sets')
_add('VERB', 'make', 'make|making|makes')
_add('VERB', 'generic', 'transform|transforming|change|changing|update|updating|modify|modifying|adjust|adjusting')
_add('VERB', 'insert', 'insert|register|store|save|append|enroll')
_add('SCALE', 2, 'double|doubling|doubled|doubles')
_add('SCALE', 3, 'triple|tripling|tripled|triples')
_add('SCALE', 4, 'quadruple|quadrupling|quadrupled|quadruples')
_add('HALVE', None, 'halve|halving|halved|halves')
_add('BECOMES', None, 'becomes|become|should become|is now|turns into|is set to|gets set to|is always|are always')
_add('MODAL', None, 'should be|must be|needs to be|is to be|gets|has to be|should get|will be')
_add('TO', None, 'to')
_add('BY', None, 'by|using|via|based on|according to')
_add('FROM', None, 'from')
_add('PRON', None, '''it|its current value|its value|its current|itself|the current value|current value
 |that value|its old value|its previous value|the old value''')

# ---- aggregates -----------------------------------------------------------------------
_add('AGG', 'avg', 'average|mean|avg|average of')
_add('AGG', 'sum', 'sum|total|sum of|total of|add up|sum up')
_add('AGG', 'count', 'count|how many|number of|the number of|count of|count up|tally|tally up')
_add('AGG', 'max', 'largest|biggest|highest|maximum|max|greatest')
_add('AGG', 'min', 'smallest|lowest|minimum|min|least')

# ---- actions --------------------------------------------------------------------------
_add('ACT', 'show', '''show|show me|list|print|print out|display|retrieve|return|returns|give me|get|fetch
 |output|produce|what are|what is|what|tell me|report|see|view|it returns|give back
 |pick|select|choose|who are|who is''')
_add('ACT', 'find', 'find|look up|lookup|search|search for|locate')
_add('ACT', 'remove', '''remove|delete|drop|discard|erase|get rid of|wipe out|throw away|throw out|purge|clear out
 |removed|deleted|removing|removes|deleting|deletes''')
_add('ACT', 'keep', 'keep|retain|keep only|only keep|retain only')
_add('ACT', 'sort', 'sort|order|arrange|rank|sorted')
_add('TAKE', None, '''take|takes|it takes|accept|accepts|it accepts|receive|receives|that takes|that accepts
 |which takes|taking''')

# ---- ordering -------------------------------------------------------------------------
_add('SORTBY', None, 'sorted by|ordered by|order by|sort by|in order of|arranged by|ranked by|by order of')
_add('DIR', 'asc', '''ascending|in ascending order|ascending order|smallest first|lowest first
 |from lowest to highest|from smallest to largest|low to high|alphabetically|in alphabetical order''')
_add('DIR', 'desc', '''descending|in descending order|descending order|largest first|highest first|biggest first
 |from highest to lowest|from largest to smallest|high to low|in reverse|reversed''')

# ---- limits ---------------------------------------------------------------------------
_add('TOP', 'desc', 'top|the top')
_add('TOP', 'asc', 'bottom|the bottom')
_add('FIRST', None, 'first|the first')
_add('PCT', None, 'percent|per cent')
_add('BETWEEN', None, 'between|is between|are between|in the range')

# ---- conditions -----------------------------------------------------------------------
_add('WHERE', None, '''whose|where|who have|that have|which have|with|having|who are|that are|which are
 |if|when|as long as|only if|for which|such that|who has|that has|which has''')
_add('CMP', 'gt', 'greater than|more than|over|above|bigger than|larger than|higher than|exceeds|exceeding')
_add('CMP', 'ge', 'at least|no less than|not less than|greater than or equal to')
_add('CMP', 'lt', 'less than|under|below|smaller than|lower than|fewer than')
_add('CMP', 'le', 'at most|no more than|not more than|less than or equal to|up to')
_add('CMP', 'eq', 'equal to|equals|exactly|same as|the same as|equal')
_add('CMP', 'ne', 'not equal to|other than|different from')
_add('CMP', 'has', 'containing|contains the text|contain the text')
_add('CMP', 'starts', 'starts with|start with|begins with|begin with|starting with|beginning with')
_add('CMP', 'ends', 'ends with|end with|ending with')
_add('NOT', None, "not|is not|isn't|are not|aren't")
_add('IS', None, 'is|are')
_add('AND', None, 'and|and also|as well as')
_add('OR', None, 'or')
_add('THEN', None, 'then|and then')
_add('GIVEN', None, '''a given|the given|given|a provided|the provided|provided|a supplied|supplied
 |a specified|the specified|specified|a certain|some given''')

# ---- single values, either-or values, standing rules -------------------------------
_add('STARTS', None, 'starts at|starts as|starts out at|starts out as|start at|begins at|is initially|starting at')
_add('OTHERWISE', None, 'otherwise|else|or else')
_add('RULE', None, 'whenever|as soon as|every time|each time|any time|the moment')

# ---- scope ----------------------------------------------------------------------------
_add('QUANT', None, '''each|every|all|for every|for each|for all|all of|all the|all of the|any|every single
 |each of|each of the|each one|every one|each of them|all of them''')
_add('GEN', None, '''everyone|everybody|person|people|item|items|entry|entries|record|records|them|they
 |member|members|element|elements''')

# ---- relationships -------------------------------------------------------------------
_add('BELONGS', None, 'belongs to|belong to|is owned by|are owned by')
_add('CANNOT', None, "cannot be|can not be|can't be|must not be|may not be|cannot|can never be|must never be")

# ---- declarations ---------------------------------------------------------------------
_add('COLLWORD', None, 'collection|collections')
_add('ISCOLL', None, '''is a collection|are a collection|is a collection of|a collection of|collection of
 |collection called|collection named''')
_add('HAS', None, '''has|have|contains|contain|consists of|includes|include|holds|is made of
 |has the following|has these''')
_add('UNIQUE', None, "unique|distinct|never repeats|never repeat|cannot repeat|can't repeat|must not repeat")
_add('NOTWO', None, 'no two')
_add('SHARE', None, 'share|shares')
_add('SAME', None, 'the same|same')
_add('INSORDER', None, '''in the order they were added|in the order they are added|the order they were added
 |insertion order|in insertion order|order of insertion|in the order of insertion|in the order added
 |order matters''')
_add('NOORDER', None, '''order does not matter|order doesn't matter|in any order|order is irrelevant
 |order is not important''')
_add('DUP', None, '''duplicate|duplicates|duplicated|already exists|already exist|already there
 |already present|on duplicate''')
_add('POLICY', 'reject', 'reject|rejected|refuse|refused|is an error|fail|fails|not allowed|disallow|forbidden')
_add('POLICY', 'replace', 'replace|replaced|replaces|overwrite|overwritten|overwrites|wins')
_add('TYPE', 'text', 'text|string|strings|textual|word|words')
_add('TYPE', 'int', 'number|numbers|integer|integers|numeric|int|whole number|whole numbers')
_add('TYPE', 'dec', 'decimal|decimals|decimal number|decimal numbers|money|amount of money')

MAX_PHRASE = max(len(k) for k in PHRASES)

SYMS = {
    '*': ('OP', 'mul'), '×': ('OP', 'mul'), '+': ('OP', 'add'), '-': ('OP', 'sub'),
    '/': ('OP', 'div'), '÷': ('OP', 'div'),
    '=': ('EQSYM', None), '==': ('CMP', 'eq'), '!=': ('CMP', 'ne'),
    '>': ('CMP', 'gt'), '<': ('CMP', 'lt'), '>=': ('CMP', 'ge'), '<=': ('CMP', 'le'),
    ':': ('COLON', None), ',': ('COMMA', None), '(': ('LP', None), ')': ('RP', None),
    '&': ('AND', None), '%': ('PCT', None),
}

# Property types the language assumes from a conventional name when nothing else decides it.
# Every such assumption is reported as a note; a declared type always wins.
CONVENTIONAL_TYPES = {
    'text': '''name email title address city country phone description label username surname
               first_name last_name email_address'''.split(),
    'int': 'age count quantity year score points level stock'.split(),
}
CONVENTION = {n: t for t, names in CONVENTIONAL_TYPES.items() for n in names}

TYPE_WORDS = {
    'text': 'text', 'string': 'text', 'strings': 'text', 'textual': 'text', 'word': 'text', 'words': 'text',
    'number': 'int', 'numbers': 'int', 'integer': 'int', 'integers': 'int', 'numeric': 'int', 'int': 'int',
    'decimal': 'dec', 'decimals': 'dec', 'money': 'dec', 'currency': 'dec',
}
# Plural words that name one number, not several values ("each player has points").
COUNT_NOUNS = set('''points units cents credits coins likes votes views stars wins losses lives hits steps
 days hours minutes seconds years months weeks goals runs sales visits clicks orders_count'''.split())

UNSUPPORTED_TYPES = {'float', 'real', 'fraction', 'date', 'boolean', 'bool'}


# Words that end in "us" and are one thing, not several: "status" stays "status", while
# "menus" and "skus" are several of a menu and a sku.
ONE_US = set('''status bonus virus campus census focus radius genus corpus nexus surplus consensus apparatus chorus
 circus minus plus bus versus thus us stimulus cactus fungus nucleus syllabus terminus abacus octopus walrus citrus
 lotus opus locus modulus calculus sinus torus fetus rebus exodus impetus hiatus prospectus discus caucus crocus
 hibiscus papyrus platypus rhombus thesaurus genius alumnus cumulus bogus onus mucus humus lupus typhus uterus
 isthmus litmus ruckus venus magus nimbus tetanus tinnitus detritus emeritus colossus esophagus hippopotamus'''.split())


def singular(w):
    if len(w) > 3 and w.endswith('ies'):
        return w[:-3] + 'y'
    if len(w) > 4 and w.endswith(('sses', 'shes', 'ches', 'xes')):
        return w[:-2]
    if w.endswith('us'):
        return w if len(w) < 4 or w in ONE_US or w.endswith('ous') else w[:-1]
    if len(w) > 2 and w.endswith('s') and not w.endswith(('ss', 'is')):
        return w[:-1]
    return w


CONVENTION.update({singular(w): 'int' for w in COUNT_NOUNS})


# ---- time, keys and the board ------------------------------------------------------
# These are read from their place in the sentence, never reserved: "the high score" and
# "each ticket has a key" stay ordinary names.
UNITS = {'millisecond': 1, 'milliseconds': 1, 'ms': 1, 'second': 1000, 'seconds': 1000,
         'minute': 60000, 'minutes': 60000}
DRAW_WORDS = {'draw', 'paint', 'plot'}
BOARD_WORDS = {'board', 'screen', 'grid'}
WIDE_WORDS = {'wide', 'across', 'columns'}
HIGH_WORDS = {'high', 'tall', 'rows'}
PRESS_VERBS = {'presses', 'press', 'hits', 'taps', 'tap'}
PRESSED = {'pressed', 'hit', 'tapped', 'held', 'down'}
LIVE_WORDS = set(UNITS) | DRAW_WORDS | BOARD_WORDS | WIDE_WORDS | HIGH_WORDS | PRESS_VERBS | PRESSED | \
    {'key', 'arrow', 'button', 'game', 'ends', 'finished', 'at', 'as', 'above', 'below'}


def all_known_words():
    return sorted({w for ph in PHRASES for w in ph} | LIVE_WORDS)
