import abc
import sys
# import pyparsing - available if you need it!
# import lark - available if you need it!
basic_char_pattern = {
    "\\d": lambda c: c.isdigit(),
    "\\w": lambda c: c.isalnum(),
    ".": lambda c: True,
}
matched_groups = [None]  # we use index 0 as a placeholder
class MatcherBase(abc.ABC):
    @abc.abstractmethod
    def _match_and_increment(self, input_line, start_idx):
        raise NotImplementedError
    def match(self, input_line, start_idx):
        predicate, new_idx = self._match_and_increment(input_line, start_idx)
        return predicate, new_idx if predicate else start_idx
class Matcher(MatcherBase):
    @staticmethod
    @abc.abstractmethod
    def parse(pattern, start_idx):
        raise NotImplementedError
    @abc.abstractmethod
    def _matcher(self, input_line, start_idx):
        raise NotImplementedError
    def _match_and_increment(self, input_line, start_idx):
        return self._matcher(input_line, start_idx), start_idx + 1
class Quantifier(MatcherBase):
    def __init__(self, matcher):
        self.matcher = matcher
class CharMatcher(Matcher):
    def __init__(self, match_fn):
        self.match_fn = match_fn
    @staticmethod
    def parse(pattern, start_idx):
        assert start_idx < len(pattern)
        pattern_char = (
            pattern[start_idx : start_idx + 2]
            if pattern[start_idx] == "\\"
            else pattern[start_idx]
        )
        return (
            CharMatcher(
                basic_char_pattern.get(pattern_char, lambda c: c == pattern_char)
            ),
            start_idx + len(pattern_char),
        )
    def _matcher(self, input_line, start_idx):
        return self.match_fn(input_line[start_idx])
class ListMatcher(Matcher):
    def __init__(self, char_set, negate):
        self.char_set = char_set
        self.negate = negate
    @staticmethod
    def parse(pattern, start_idx):
        if pattern[start_idx] != "[":
            return None, start_idx
        assert start_idx + 1 < len(pattern)
        char_set = set()
        negate = pattern[start_idx + 1] == "^"
        i = start_idx + (2 if negate else 1)
        while i < len(pattern):
            if pattern[i] == "]":
                break
            char_set.add(pattern[i])
            i += 1
        else:
            raise RuntimeError(f"Missing ']': {pattern}")
        return ListMatcher(char_set, negate), i + 1
    def _matcher(self, input_line, start_idx):
        return (input_line[start_idx] in self.char_set) ^ self.negate
class StartMatcher(Matcher):
    @staticmethod
    def parse(pattern, start_idx):
        assert start_idx == 0 and pattern[0] == "^"
        return StartMatcher(), start_idx + 1
    def _match_and_increment(self, input_line, start_idx):
        return (
            self._matcher(input_line, start_idx),
            start_idx,
        )  # No Increment for StartMatcher
    def _matcher(self, input_line, start_idx):
        return start_idx == 0
class EndMatcher(Matcher):
    @staticmethod
    def parse(pattern, start_idx):
        assert start_idx == len(pattern) - 1 and pattern[-1] == "$"
        return EndMatcher(), start_idx + 1
    def _match_and_increment(self, input_line, start_idx):
        return (
            self._matcher(input_line, start_idx),
            start_idx,
        )  # No Increment for EndMatcher
    def _matcher(self, input_line, start_idx):
        return start_idx == len(input_line)
class OneOrMoreQuantifier(Quantifier):
    def __init__(self, matcher):
        super().__init__(matcher)
        self.lookahead = None
    def set_lookahead(self, lookahead):
        self.lookahead = lookahead
    def _match_and_increment(self, input_line, start_idx):
        print(
            f"Match one or more of {self.matcher} with lookahead={self.lookahead}",
            file=sys.stderr,
        )
        lookahead_match = False
        is_match, i = self.matcher.match(input_line, start_idx)
        if not is_match:
            return False, start_idx
        if self.lookahead and i < len(input_line):
            lookahead_match, _ = self.lookahead.match(input_line, i)
        while i < len(input_line) and is_match and not lookahead_match:
            is_match, i = self.matcher.match(input_line, i)
            if self.lookahead and i < len(input_line):
                lookahead_match, _ = self.lookahead.match(input_line, i)
        return True, i
class OneOrNoneQuantifier(Quantifier):
    def _match_and_increment(self, input_line, start_idx):
        is_match, i = self.matcher.match(input_line, start_idx)
        return True, i if is_match else start_idx
class GroupMatcher(Matcher):
    def __init__(self, matchers):
        self.matchers = matchers
    @staticmethod
    def parse(pattern, start_idx):
        assert start_idx < len(pattern) and pattern[start_idx] == "("
        matchers = []
        start_idx += 1
        depth = 0
        while start_idx < len(pattern):
            if pattern[start_idx] == ")":
                break
            elif pattern[start_idx] == "(":
                depth += 1
            end = start_idx + 1
            while end < len(pattern):
                if pattern[end] in [")", "|"] and depth == 0:
                    break
                if pattern[end] == "(":
                    depth += 1
                elif pattern[end] == ")":
                    depth -= 1
                end += 1
            matchers.append(parse_pattern(pattern[start_idx:end]))
            start_idx = end if pattern[end] == ")" else end + 1
        else:
            raise RuntimeError(f"Missing ): {pattern}")
        return GroupMatcher(matchers), start_idx + 1
    def set_lookahead(self, lookahead):
        assert self.matchers
        print(f"Group: {self.matchers}")
        for match_list in self.matchers:
            if isinstance(match_list[-1], OneOrMoreQuantifier):
                print(f"Set lookahead {lookahead} for matcher {match_list[-1]}")
                match_list[-1].set_lookahead(lookahead)
    def _matcher(self, input_line, start_idx):
        pass
    def _match_and_increment(self, input_line, start_idx):
        i = start_idx
        for m in self.matchers:
            ok, i = all_matchers_pass(m, input_line, start_idx)
            if ok:
                break
        else:
            return False, start_idx
        return True, i
class ReferenceMatcher(Matcher):
    def __init__(self, num):
        self.num = num
    @staticmethod
    def parse(pattern, start_idx):
        assert is_reference(pattern[start_idx:])
        return ReferenceMatcher(int(pattern[start_idx:][1])), start_idx + 2
    def _match_and_increment(self, input_line, start_idx):
        if self.num >= len(matched_groups):
            raise RuntimeError(f"missing reference: {input_line}")
        return self._matcher(input_line, start_idx), start_idx + len(
            matched_groups[self.num]
        )
    def _matcher(self, input_line, start_idx):
        return input_line[start_idx:].startswith(matched_groups[self.num])
def get_matcher_class(pattern_char):
    return {
        "[": ListMatcher,
        "^": StartMatcher,
        "$": EndMatcher,
        "(": GroupMatcher,
    }.get(pattern_char, CharMatcher)
def get_quantifier_class(pattern_char):
    return {
        "+": OneOrMoreQuantifier,
        "?": OneOrNoneQuantifier,
    }.get(pattern_char, None)
def is_reference(pattern):
    return len(pattern) >= 2 and pattern[0] == "\\" and pattern[1].isdigit()
def parse_pattern(pattern):
    i = 0
    matchers = []
    while i < len(pattern):
        quantifier = get_quantifier_class(pattern[i])
        if quantifier:
            assert matchers
            matchers[-1] = quantifier(matchers[-1])
            i += 1
        elif is_reference(pattern[i:]):
            matcher, i = ReferenceMatcher.parse(pattern, i)
            matchers.append(matcher)
        else:
            matcher, i = get_matcher_class(pattern[i]).parse(pattern, i)
            if not matcher:
                raise RuntimeError(f"Unhandled pattern: {pattern}")
            matchers.append(matcher)
    # Add lookaheads for quantifiers
    for i, m in enumerate(matchers):
        print(f"{m}", file=sys.stderr)
        if (
            isinstance(m, OneOrMoreQuantifier) or isinstance(m, GroupMatcher)
        ) and i + 1 < len(matchers):
            print(f"Set lookahead {matchers[i + 1]} for {m}", file=sys.stderr)
            m.set_lookahead(matchers[i + 1])
    return matchers
def all_matchers_pass(matchers, input_line, start):
    global matched_groups
    i = start
    match_idx = 0
    while i < len(input_line) and match_idx < len(matchers):
        if isinstance(matchers[match_idx], GroupMatcher):
            # Save the last index
            group_index = len(matched_groups)
            matched_groups.append(None)
            is_match, next_i = matchers[match_idx].match(input_line, i)
            if is_match:
                print(
                    f"Matched {input_line[i:next_i]} as group for index {group_index}",
                    file=sys.stderr,
                )
                matched_groups[group_index] = input_line[i:next_i]
            else:
                matched_groups = matched_groups[:group_index]
        else:
            is_match, next_i = matchers[match_idx].match(input_line, i)
        if is_match:
            match_idx += 1
            i = next_i
        else:
            break
    else:
        # Ignore all optional matchers
        while match_idx < len(matchers) and isinstance(
            matchers[match_idx], OneOrNoneQuantifier
        ):
            match_idx += 1
        if match_idx == len(matchers) - 1 and isinstance(matchers[-1], EndMatcher):
            is_match, i = matchers[-1].match(input_line, i)
            return is_match, i
        return match_idx == len(matchers), i
    return False, i
def match_pattern(input_line, pattern):
    matchers = parse_pattern(pattern)
    if isinstance(matchers[0], StartMatcher):
        ok, _ = all_matchers_pass(matchers, input_line, 0)
        return ok
    i = 0
    while i < len(input_line):
        ok, _ = all_matchers_pass(matchers, input_line, i)
        if ok:
            break
        matched_groups = [None]  # reset references
        i += 1
    else:
        return False
    return True
def main():
    pattern = sys.argv[2]
    input_line = sys.stdin.read()
    if sys.argv[1] != "-E":
        print("Expected first argument to be '-E'")
        exit(1)
    if match_pattern(input_line, pattern):
        exit(0)
    else:
        exit(1)
if __name__ == "__main__":
    main()