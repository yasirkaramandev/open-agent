import { useCallback, useEffect, useRef, useState } from 'react';
import { CalcError, compute } from '../calculator';
import { Display } from './Display';
import { Keypad, type CalculatorAction } from './Keypad';

type Operator = '+' | '-' | '*' | '/';

const MAX_ENTRY_LENGTH = 16;

const errorMessages: Record<string, string> = {
  DivisionByZero: 'Cannot divide by zero',
  DomainError: 'That value is outside the valid range',
  Overflow: 'Result is too large',
  SyntaxError: 'Check the expression',
  InvalidFactorial: 'Factorial needs a positive whole number',
  MismatchedParens: 'Check the parentheses',
};

function operatorLabel(operator: string) {
  if (operator === '*') return '×';
  if (operator === '/') return '÷';
  if (operator === '-') return '−';
  return operator;
}

function expressionLabel(parts: readonly string[]) {
  return parts.map(operatorLabel).join(' ');
}

function displayNumber(value: string) {
  if (value.includes('e')) return value.replace('-', '−');

  const isNegative = value.startsWith('-');
  const unsigned = isNegative ? value.slice(1) : value;
  const [integer = '0', decimal] = unsigned.split('.');
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const formatted = decimal === undefined ? grouped : `${grouped}.${decimal}`;
  return isNegative ? `−${formatted}` : formatted;
}

function getActionId(action: CalculatorAction) {
  switch (action.type) {
    case 'digit':
      return action.value;
    case 'operator':
      return action.value;
    case 'decimal':
      return '.';
    case 'equals':
      return 'equals';
    default:
      return action.type;
  }
}

function keyboardAction(key: string): CalculatorAction | null {
  if (/^\d$/.test(key)) return { type: 'digit', value: key };
  if (key === '.' || key === ',') return { type: 'decimal' };
  if (key === '+' || key === '-') return { type: 'operator', value: key };
  if (key === '*' || key.toLowerCase() === 'x') {
    return { type: 'operator', value: '*' };
  }
  if (key === '/') return { type: 'operator', value: '/' };
  if (key === 'Enter' || key === '=') return { type: 'equals' };
  if (key === 'Escape') return { type: 'clear' };
  if (key === 'Delete') return { type: 'clearEntry' };
  if (key === 'Backspace') return { type: 'backspace' };
  if (key === '%') return { type: 'percent' };
  return null;
}

function messageForError(error: unknown) {
  if (error instanceof CalcError) {
    return errorMessages[error.code] ?? 'Unable to calculate';
  }
  return 'Unable to calculate';
}

export function Calculator() {
  const [parts, setParts] = useState<string[]>([]);
  const [entry, setEntry] = useState('0');
  const [entryStarted, setEntryStarted] = useState(false);
  const [history, setHistory] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [justEvaluated, setJustEvaluated] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const keyTimer = useRef<number | null>(null);

  const clearAll = useCallback(() => {
    setParts([]);
    setEntry('0');
    setEntryStarted(false);
    setHistory('');
    setError(null);
    setJustEvaluated(false);
  }, []);

  const runCalculation = useCallback(
    (expressionParts: readonly string[]) => {
      const expression = expressionParts.join(' ');
      try {
        const result = compute(expression);
        setEntry(result.formatted);
        setEntryStarted(true);
        setParts([]);
        setHistory(`${expressionLabel(expressionParts)} =`);
        setError(null);
        setJustEvaluated(true);
      } catch (calculationError) {
        setHistory(`${expressionLabel(expressionParts)} =`);
        setError(messageForError(calculationError));
        setJustEvaluated(true);
      }
    },
    [],
  );

  const handleAction = useCallback(
    (action: CalculatorAction) => {
      if (action.type === 'clear') {
        clearAll();
        return;
      }

      if (error) {
        if (action.type === 'backspace' || action.type === 'clearEntry') {
          clearAll();
          return;
        }
        clearAll();
      }

      if (action.type === 'digit') {
        const beginNew = justEvaluated;
        const current = beginNew ? '0' : entry;
        const hasStarted = beginNew ? false : entryStarted;
        const digitCount = current.replace(/[-.]/g, '').length;

        if (digitCount >= MAX_ENTRY_LENGTH && hasStarted) return;

        setParts(beginNew ? [] : parts);
        setHistory(beginNew ? '' : history);
        setJustEvaluated(false);
        setEntryStarted(true);

        if (!hasStarted || current === '0') {
          setEntry(action.value);
        } else if (current === '-0') {
          setEntry(`-${action.value}`);
        } else {
          setEntry(`${current}${action.value}`);
        }
        return;
      }

      if (action.type === 'decimal') {
        const beginNew = justEvaluated;
        const current = beginNew ? '0' : entry;
        if (!beginNew && entryStarted && current.includes('.')) return;

        setParts(beginNew ? [] : parts);
        setHistory(beginNew ? '' : history);
        setJustEvaluated(false);
        setEntryStarted(true);
        setEntry(
          !beginNew && entryStarted
            ? `${current}.`
            : current === '-0'
              ? '-0.'
              : '0.',
        );
        return;
      }

      if (action.type === 'operator') {
        const operator: Operator = action.value;

        if (justEvaluated) {
          setParts([entry, operator]);
          setHistory('');
          setEntryStarted(false);
          setJustEvaluated(false);
          return;
        }

        if (entryStarted || parts.length === 0) {
          setParts([...parts, entry, operator]);
          setEntryStarted(false);
        } else {
          setParts([...parts.slice(0, -1), operator]);
        }
        return;
      }

      if (action.type === 'equals') {
        if (parts.length === 0) {
          setHistory(`${displayNumber(entry)} =`);
          setJustEvaluated(true);
          return;
        }
        if (!entryStarted) return;
        runCalculation([...parts, entry]);
        return;
      }

      if (action.type === 'clearEntry') {
        setEntry('0');
        setEntryStarted(false);
        setHistory(justEvaluated ? '' : history);
        setJustEvaluated(false);
        return;
      }

      if (action.type === 'backspace') {
        if (justEvaluated) {
          clearAll();
          return;
        }

        if (!entryStarted) {
          if (parts.length >= 2) {
            const previousEntry = parts.at(-2) ?? '0';
            setParts(parts.slice(0, -2));
            setEntry(previousEntry);
            setEntryStarted(true);
          }
          return;
        }

        const next = entry.slice(0, -1);
        if (next === '' || next === '-') {
          setEntry('0');
          setEntryStarted(false);
        } else {
          setEntry(next);
        }
        return;
      }

      if (action.type === 'sign') {
        setHistory(justEvaluated ? '' : history);
        setJustEvaluated(false);
        setEntryStarted(true);
        setEntry(entry.startsWith('-') ? entry.slice(1) : `-${entry}`);
        return;
      }

      if (action.type === 'percent') {
        try {
          const lastOperator = parts.at(-1);
          const baseParts = parts.slice(0, -1);
          const percentExpression =
            (lastOperator === '+' || lastOperator === '-') &&
            baseParts.length > 0
              ? `(${baseParts.join(' ')}) * (${entry}) / 100`
              : `(${entry}) / 100`;
          const result = compute(percentExpression);
          setEntry(result.formatted);
          setEntryStarted(true);
          setHistory(justEvaluated ? '' : history);
          setJustEvaluated(false);
        } catch (calculationError) {
          setError(messageForError(calculationError));
          setJustEvaluated(true);
        }
      }
    },
    [
      clearAll,
      entry,
      entryStarted,
      error,
      history,
      justEvaluated,
      parts,
      runCalculation,
    ],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const action = keyboardAction(event.key);
      if (!action) return;

      event.preventDefault();
      handleAction(action);
      setActiveKey(getActionId(action));
      if (keyTimer.current !== null) window.clearTimeout(keyTimer.current);
      keyTimer.current = window.setTimeout(() => setActiveKey(null), 110);
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      if (keyTimer.current !== null) window.clearTimeout(keyTimer.current);
    };
  }, [handleAction]);

  const pendingExpression =
    history ||
    expressionLabel([
      ...parts,
      ...(entryStarted && parts.length > 0 ? [displayNumber(entry)] : []),
    ]);

  return (
    <section className="calculator" aria-label="Standard calculator">
      <div className="calculator__topline">
        <span>OPENCALC / 01</span>
        <span className="calculator__precision">12-digit precision</span>
      </div>

      <Display
        expression={pendingExpression}
        result={error ?? displayNumber(entry)}
        isError={error !== null}
      />

      <Keypad onAction={handleAction} activeKey={activeKey} />
    </section>
  );
}
