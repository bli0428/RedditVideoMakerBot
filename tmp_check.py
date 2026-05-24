from utils.story_splitter.boundaries import _find_sentence_terminator, _advance_past_whitespace
import re

part1_body = 'A' * 69 + '. '
part2_body = 'B' * 28 + '. '
tail_body  = 'C' * 19
post = part1_body + part2_body + tail_body
print('len(post):', len(post))

pat = re.compile(r'[.!?](?=\s)')
for m in pat.finditer(post):
    boundary = m.end()
    ts = _advance_past_whitespace(post, boundary, 'sentence')
    print(f'terminator at {m.start()}, boundary at {boundary}, tail_start={ts}, tail_len={len(post)-ts}')

# Also check the multi-iteration scenario
print()
seg_a = 'A' * 59 + '. '
seg_b = 'B' * 19 + '. '
seg_c = 'C' * 29 + '. '
seg_d = 'D' * 20
post2 = seg_a + seg_b + seg_c + seg_d
print('len(post2):', len(post2))
for m in pat.finditer(post2):
    boundary = m.end()
    ts = _advance_past_whitespace(post2, boundary, 'sentence')
    print(f'terminator at {m.start()}, boundary at {boundary}, tail_start={ts}, tail_len={len(post2)-ts}')
