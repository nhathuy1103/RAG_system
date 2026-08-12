const MAX_DIFF_LINES = 400;
const GAP_PENALTY = -0.45;

const NEGATION_WORDS = new Set([
  "khong",
  "chua",
  "cam",
  "not",
  "never",
  "forbidden",
  "prohibited",
]);

function fold(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/^\s*\d+[.)]\s+/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function tokens(value) {
  return fold(value).match(/[a-z0-9]+(?:[.,][0-9]+)*/g) || [];
}

function numbers(value) {
  return tokens(value).filter((token) => /^\d/.test(token));
}

function negations(value) {
  return tokens(value).filter((token) => NEGATION_WORDS.has(token));
}

function diceCoefficient(left, right) {
  if (left === right) return 1;
  if (left.length < 2 || right.length < 2) return 0;
  const pairs = new Map();
  for (let index = 0; index < left.length - 1; index += 1) {
    const pair = left.slice(index, index + 2);
    pairs.set(pair, (pairs.get(pair) || 0) + 1);
  }
  let overlap = 0;
  for (let index = 0; index < right.length - 1; index += 1) {
    const pair = right.slice(index, index + 2);
    const count = pairs.get(pair) || 0;
    if (count > 0) {
      overlap += 1;
      pairs.set(pair, count - 1);
    }
  }
  return (2 * overlap) / (left.length + right.length - 2);
}

export function lineSimilarity(left, right) {
  const foldedLeft = fold(left);
  const foldedRight = fold(right);
  if (!foldedLeft || !foldedRight) return 0;
  if (foldedLeft === foldedRight) return 1;
  const leftTokens = new Set(tokens(left));
  const rightTokens = new Set(tokens(right));
  const union = new Set([...leftTokens, ...rightTokens]);
  const intersection = [...leftTokens].filter((token) => rightTokens.has(token));
  const tokenScore = union.size ? intersection.length / union.size : 0;
  return Math.min(
    1,
    Math.max(0, tokenScore * 0.68 + diceCoefficient(foldedLeft, foldedRight) * 0.32),
  );
}

function splitLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function pairScore(left, right) {
  const similarity = lineSimilarity(left, right);
  if (similarity === 1) return 3;
  if (similarity >= 0.72) return 0.7 + similarity * 1.5;
  if (similarity >= 0.46) return similarity;
  return -1.1;
}

function alignLines(sourceLines, targetLines) {
  const sourceCount = sourceLines.length;
  const targetCount = targetLines.length;
  const scores = Array.from(
    { length: sourceCount + 1 },
    () => new Float64Array(targetCount + 1),
  );
  const decisions = Array.from(
    { length: sourceCount + 1 },
    () => new Uint8Array(targetCount + 1),
  );
  for (let sourceIndex = 1; sourceIndex <= sourceCount; sourceIndex += 1) {
    scores[sourceIndex][0] = sourceIndex * GAP_PENALTY;
    decisions[sourceIndex][0] = 2;
  }
  for (let targetIndex = 1; targetIndex <= targetCount; targetIndex += 1) {
    scores[0][targetIndex] = targetIndex * GAP_PENALTY;
    decisions[0][targetIndex] = 3;
  }
  for (let sourceIndex = 1; sourceIndex <= sourceCount; sourceIndex += 1) {
    for (let targetIndex = 1; targetIndex <= targetCount; targetIndex += 1) {
      const paired = scores[sourceIndex - 1][targetIndex - 1]
        + pairScore(sourceLines[sourceIndex - 1], targetLines[targetIndex - 1]);
      const sourceOnly = scores[sourceIndex - 1][targetIndex] + GAP_PENALTY;
      const targetOnly = scores[sourceIndex][targetIndex - 1] + GAP_PENALTY;
      const maximum = Math.max(paired, sourceOnly, targetOnly);
      scores[sourceIndex][targetIndex] = maximum;
      decisions[sourceIndex][targetIndex] = maximum === paired
        ? 1
        : (maximum === sourceOnly ? 2 : 3);
    }
  }

  const output = [];
  let sourceIndex = sourceCount;
  let targetIndex = targetCount;
  while (sourceIndex > 0 || targetIndex > 0) {
    const decision = decisions[sourceIndex][targetIndex];
    if (decision === 1) {
      output.push({
        source: sourceLines[sourceIndex - 1],
        target: targetLines[targetIndex - 1],
        sourceLineNumber: sourceIndex,
        targetLineNumber: targetIndex,
      });
      sourceIndex -= 1;
      targetIndex -= 1;
    } else if (decision === 2 || targetIndex === 0) {
      output.push({
        source: sourceLines[sourceIndex - 1],
        target: "",
        sourceLineNumber: sourceIndex,
        targetLineNumber: null,
      });
      sourceIndex -= 1;
    } else {
      output.push({
        source: "",
        target: targetLines[targetIndex - 1],
        sourceLineNumber: null,
        targetLineNumber: targetIndex,
      });
      targetIndex -= 1;
    }
  }
  return output.reverse();
}

function inlineTokens(value) {
  return String(value || "").match(/\s+|[\p{L}\p{N}]+(?:[.,]\d+)?|[^\s\p{L}\p{N}]/gu) || [];
}

function comparableToken(value) {
  return fold(value).replace(/\s+/g, "");
}

export function diffInlineSegments(left, right) {
  const leftTokens = inlineTokens(left);
  const rightTokens = inlineTokens(right);
  const rows = leftTokens.length + 1;
  const columns = rightTokens.length + 1;
  const dp = Array.from({ length: rows }, () => new Uint16Array(columns));
  for (let leftIndex = leftTokens.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = rightTokens.length - 1; rightIndex >= 0; rightIndex -= 1) {
      const leftComparable = comparableToken(leftTokens[leftIndex]);
      const rightComparable = comparableToken(rightTokens[rightIndex]);
      dp[leftIndex][rightIndex] = leftComparable === rightComparable
        ? dp[leftIndex + 1][rightIndex + 1] + 1
        : Math.max(dp[leftIndex + 1][rightIndex], dp[leftIndex][rightIndex + 1]);
    }
  }
  const leftSegments = [];
  const rightSegments = [];
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < leftTokens.length || rightIndex < rightTokens.length) {
    const leftToken = leftTokens[leftIndex];
    const rightToken = rightTokens[rightIndex];
    if (
      leftIndex < leftTokens.length
      && rightIndex < rightTokens.length
      && comparableToken(leftToken) === comparableToken(rightToken)
    ) {
      leftSegments.push({ text: leftToken, changed: false });
      rightSegments.push({ text: rightToken, changed: false });
      leftIndex += 1;
      rightIndex += 1;
    } else if (
      rightIndex >= rightTokens.length
      || (leftIndex < leftTokens.length
        && dp[leftIndex + 1][rightIndex] >= dp[leftIndex][rightIndex + 1])
    ) {
      leftSegments.push({ text: leftToken, changed: !/^\s+$/.test(leftToken) });
      leftIndex += 1;
    } else {
      rightSegments.push({ text: rightToken, changed: !/^\s+$/.test(rightToken) });
      rightIndex += 1;
    }
  }
  return { source: leftSegments, target: rightSegments };
}

function classifyRow(row, relationType) {
  if (!row.source) {
    return { kind: "target_only", severity: "medium", label: "Chỉ có ở tài liệu phát hiện" };
  }
  if (!row.target) {
    return { kind: "source_only", severity: "medium", label: "Chỉ có ở tài liệu hiện hành" };
  }
  const similarity = lineSimilarity(row.source, row.target);
  if (similarity === 1) {
    return { kind: "exact", severity: "none", label: "Trùng khớp", similarity };
  }
  const numberMismatch = JSON.stringify(numbers(row.source)) !== JSON.stringify(numbers(row.target));
  const negationMismatch = JSON.stringify(negations(row.source)) !== JSON.stringify(negations(row.target));
  const conflictRelation = ["conflict", "conflict_candidate"].includes(relationType);
  if (numberMismatch || negationMismatch || (conflictRelation && similarity >= 0.46)) {
    return {
      kind: "conflict",
      severity: "high",
      label: numberMismatch
        ? "Mâu thuẫn số liệu"
        : (negationMismatch ? "Mâu thuẫn ý nghĩa" : "Nội dung mâu thuẫn"),
      similarity,
    };
  }
  if (similarity >= 0.78) {
    return { kind: "near", severity: "low", label: "Khác biệt nhẹ", similarity };
  }
  if (similarity >= 0.46) {
    return { kind: "near", severity: "medium", label: "Khác biệt đáng chú ý", similarity };
  }
  return { kind: "changed", severity: "medium", label: "Nội dung khác nhau", similarity };
}

export function buildEnterpriseDocumentDiff(sourceText, targetText, relationType = "") {
  const allSourceLines = splitLines(sourceText);
  const allTargetLines = splitLines(targetText);
  const sourceLines = allSourceLines.slice(0, MAX_DIFF_LINES);
  const targetLines = allTargetLines.slice(0, MAX_DIFF_LINES);
  const rows = alignLines(sourceLines, targetLines).map((row, index) => {
    const classification = classifyRow(row, relationType);
    return {
      ...row,
      ...classification,
      id: `diff-${index}-${row.sourceLineNumber || 0}-${row.targetLineNumber || 0}`,
      inline: diffInlineSegments(row.source, row.target),
    };
  });
  const counts = rows.reduce(
    (summary, row) => ({ ...summary, [row.kind]: (summary[row.kind] || 0) + 1 }),
    { exact: 0, near: 0, conflict: 0, changed: 0, source_only: 0, target_only: 0 },
  );
  const alignedRows = rows.filter((row) => row.source && row.target);
  const averageSimilarity = alignedRows.length
    ? alignedRows.reduce((total, row) => total + (row.similarity || 0), 0) / alignedRows.length
    : 0;
  return {
    rows,
    counts,
    averageSimilarity,
    sourceTruncated: allSourceLines.length > sourceLines.length,
    targetTruncated: allTargetLines.length > targetLines.length,
    maxLines: MAX_DIFF_LINES,
  };
}
