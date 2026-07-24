import { useCallback, useEffect, useRef, useState } from 'react';
import { CalcError, compute, format } from '../calculator';
import { Display } from './Display';
import { HistoryPanel } from './HistoryPanel';
import { Keypad, type CalculatorAction } from './Keypad';
import { ScientificKeypad, type ScientificAction } from './ScientificKeypad';
import { SettingsPanel } from './SettingsPanel';
import { useCalculatorHistory, type HistoryEntry } from './history';
import type { CalculatorSettings } from './settings';

type Operator = '+' | '-' | '*' | '/' | '^';
type PanelName = 'history' | 'settings';
type MemoryAction = 'clear' | 'recall' | 'add' | 'subtract' | 'store';

interface CalculatorProps {
  settings: CalculatorSettings;
  onSettingsChange: (updates: Partial<CalculatorSettings>) => void;
}

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
  if (operator === '^') return '^';
  return operator;
}

function expressionLabel(parts: readonly string[]) {
  return parts.map(operatorLabel).join(' ');
}

function displayNumber(value: string, grouping: boolean) {
  if (/[eE]/.test(value)) return value.replace('-', '−');

  const isNegative = value.startsWith('-');
  const unsigned = isNegative ? value.slice(1) : value;
  const [integer = '0', decimal] = unsigned.split('.');
  const grouped = grouping
    ? integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    : integer;
  const formatted = decimal === undefined ? grouped : `${grouped}.${decimal}`;
  return isNegative ? `−${formatted}` : formatted;
}

function formatResult(value: number, settings: CalculatorSettings) {
  return format(value, {
    precision: settings.decimalPlaces + 1,
    notation: 'fixed',
    decimalSeparator: '.',
    groupSeparator: settings.digitGrouping ? ',' : '',
  }).replace('-', '−');
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
  if (key === '^') return { type: 'operator', value: '^' };
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

export function Calculator({
  settings,
  onSettingsChange,
}: CalculatorProps) {
  const [parts, setParts] = useState<string[]>([]);
  const [entry, setEntry] = useState('0');
  const [entryToken, setEntryToken] = useState('0');
  const [entryStarted, setEntryStarted] = useState(false);
  const [entryIsResult, setEntryIsResult] = useState(false);
  const [displayExpression, setDisplayExpression] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [justEvaluated, setJustEvaluated] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [mode, setMode] = useState<'STD' | 'SCI'>('STD');
  const [openPanel, setOpenPanel] = useState<PanelName | null>(null);
  const [memory, setMemory] = useState<string | null>(null);
  const [recalledExpression, setRecalledExpression] = useState<string | null>(
    null,
  );
  const keyTimer = useRef<number | null>(null);
  const { entries, addEntry, removeEntry, clearEntries } =
    useCalculatorHistory(settings.privateMode);

  const clearAll = useCallback(() => {
    setParts([]);
    setEntry('0');
    setEntryToken('0');
    setEntryStarted(false);
    setEntryIsResult(false);
    setDisplayExpression('');
    setError(null);
    setJustEvaluated(false);
    setRecalledExpression(null);
  }, []);

  const runCalculation = useCallback(
    (expressionParts: readonly string[]) => {
      const expression = expressionParts.join(' ');
      try {
        const result = compute(expression, {
          angleMode: settings.angleMode,
          precision: 12,
        });
        setEntry(result.formatted);
        setEntryToken(result.formatted);
        setEntryStarted(true);
        setEntryIsResult(true);
        setParts([]);
        setDisplayExpression(`${expressionLabel(expressionParts)} =`);
        setError(null);
        setJustEvaluated(true);
        setRecalledExpression(null);
        addEntry(expression, result.formatted);
      } catch (calculationError) {
        setDisplayExpression(`${expressionLabel(expressionParts)} =`);
        setError(messageForError(calculationError));
        setJustEvaluated(true);
      }
    },
    [addEntry, settings.angleMode],
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
        const beginNew = justEvaluated || recalledExpression !== null;
        const current = beginNew ? '0' : entry;
        const hasStarted = beginNew ? false : entryStarted;
        const digitCount = current.replace(/[-.]/g, '').length;

        if (digitCount >= MAX_ENTRY_LENGTH && hasStarted) return;

        setParts(beginNew ? [] : parts);
        setDisplayExpression(beginNew ? '' : displayExpression);
        setJustEvaluated(false);
        setEntryStarted(true);
        setEntryIsResult(false);
        setRecalledExpression(null);

        let nextEntry: string;
        if (!hasStarted || current === '0') {
          nextEntry = action.value;
        } else if (current === '-0') {
          nextEntry = `-${action.value}`;
        } else {
          nextEntry = `${current}${action.value}`;
        }
        setEntry(nextEntry);
        setEntryToken(nextEntry);
        return;
      }

      if (action.type === 'decimal') {
        const beginNew = justEvaluated || recalledExpression !== null;
        const current = beginNew ? '0' : entry;
        if (!beginNew && entryStarted && current.includes('.')) return;

        setParts(beginNew ? [] : parts);
        setDisplayExpression(beginNew ? '' : displayExpression);
        setJustEvaluated(false);
        setEntryStarted(true);
        setEntryIsResult(false);
        setRecalledExpression(null);
        const nextEntry =
          !beginNew && entryStarted
            ? `${current}.`
            : current === '-0'
              ? '-0.'
              : '0.';
        setEntry(nextEntry);
        setEntryToken(nextEntry);
        return;
      }

      if (action.type === 'operator') {
        const operator: Operator = action.value;

        if (justEvaluated || recalledExpression !== null) {
          setParts([entry, operator]);
          setDisplayExpression('');
          setEntryStarted(false);
          setEntryIsResult(true);
          setJustEvaluated(false);
          setRecalledExpression(null);
          return;
        }

        if (entryStarted || parts.length === 0) {
          setParts([...parts, entryToken, operator]);
          setEntryStarted(false);
        } else {
          setParts([...parts.slice(0, -1), operator]);
        }
        return;
      }

      if (action.type === 'equals') {
        if (recalledExpression !== null) {
          runCalculation([recalledExpression]);
          return;
        }
        if (parts.length === 0) {
          if (justEvaluated) return;
          runCalculation([entryToken]);
          return;
        }
        if (!entryStarted) return;
        runCalculation([...parts, entryToken]);
        return;
      }

      if (action.type === 'clearEntry') {
        setEntry('0');
        setEntryToken('0');
        setEntryStarted(false);
        setEntryIsResult(false);
        setDisplayExpression(justEvaluated ? '' : displayExpression);
        setJustEvaluated(false);
        setRecalledExpression(null);
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
            try {
              const previous = compute(previousEntry, {
                angleMode: settings.angleMode,
                precision: 12,
              });
              setEntry(previous.formatted);
              setEntryToken(previousEntry);
              setEntryIsResult(previousEntry !== previous.formatted);
            } catch {
              clearAll();
              return;
            }
            setEntryStarted(true);
          }
          return;
        }

        if (entryToken !== entry) {
          setEntry('0');
          setEntryToken('0');
          setEntryStarted(false);
          setEntryIsResult(false);
          return;
        }
        const next = entry.slice(0, -1);
        if (next === '' || next === '-') {
          setEntry('0');
          setEntryToken('0');
          setEntryStarted(false);
        } else {
          setEntry(next);
          setEntryToken(next);
        }
        setEntryIsResult(false);
        return;
      }

      if (action.type === 'sign') {
        const nextEntry = entry.startsWith('-') ? entry.slice(1) : `-${entry}`;
        const nextToken = entryToken.startsWith('-')
          ? entryToken.slice(1)
          : `-(${entryToken})`;
        setDisplayExpression(justEvaluated ? '' : displayExpression);
        setJustEvaluated(false);
        setEntryStarted(true);
        setEntryIsResult(false);
        setEntry(nextEntry);
        setEntryToken(nextToken);
        setRecalledExpression(null);
        return;
      }

      if (action.type === 'percent') {
        try {
          const lastOperator = parts.at(-1);
          const baseParts = parts.slice(0, -1);
          const percentExpression =
            (lastOperator === '+' || lastOperator === '-') &&
            baseParts.length > 0
              ? `(${baseParts.join(' ')}) * (${entryToken}) / 100`
              : `(${entryToken}) / 100`;
          const result = compute(percentExpression, {
            angleMode: settings.angleMode,
            precision: 12,
          });
          setEntry(result.formatted);
          setEntryToken(result.formatted);
          setEntryStarted(true);
          setEntryIsResult(true);
          setDisplayExpression(justEvaluated ? '' : displayExpression);
          setJustEvaluated(false);
          setRecalledExpression(null);
        } catch (calculationError) {
          setError(messageForError(calculationError));
          setJustEvaluated(true);
        }
      }
    },
    [
      clearAll,
      entry,
      entryToken,
      entryStarted,
      error,
      displayExpression,
      justEvaluated,
      parts,
      recalledExpression,
      runCalculation,
      settings.angleMode,
    ],
  );

  const handleScientificAction = useCallback(
    (action: ScientificAction) => {
      if (action.type === 'power') {
        handleAction({ type: 'operator', value: '^' });
        return;
      }

      if (action.type === 'constant') {
        try {
          const result = compute(action.name, {
            angleMode: settings.angleMode,
            precision: 12,
          });
          setEntry(result.formatted);
          setEntryToken(action.name);
          setEntryStarted(true);
          setEntryIsResult(true);
          setDisplayExpression('');
          setError(null);
          setJustEvaluated(false);
          setRecalledExpression(null);
        } catch (calculationError) {
          setError(messageForError(calculationError));
        }
        return;
      }

      const operand = recalledExpression ?? entryToken;
      const expression =
        action.type === 'function'
          ? `${action.name}(${operand})`
          : action.type === 'square'
            ? `(${operand})^2`
            : action.type === 'reciprocal'
              ? `1/(${operand})`
              : `(${operand})!`;
      runCalculation([expression]);
    },
    [
      entryToken,
      handleAction,
      recalledExpression,
      runCalculation,
      settings.angleMode,
    ],
  );

  const handleMemory = useCallback(
    (action: MemoryAction) => {
      if (action === 'clear') {
        setMemory(null);
        return;
      }
      if (action === 'recall') {
        if (memory === null) return;
        setEntry(memory);
        setEntryToken(memory);
        setEntryStarted(true);
        setEntryIsResult(true);
        setDisplayExpression('');
        setError(null);
        setJustEvaluated(false);
        setRecalledExpression(null);
        return;
      }
      if (action === 'store') {
        setMemory(entry);
        return;
      }

      try {
        const expression = `${memory ?? '0'} ${
          action === 'add' ? '+' : '-'
        } (${entry})`;
        const result = compute(expression, {
          angleMode: settings.angleMode,
          precision: 12,
        });
        setMemory(result.formatted);
      } catch (calculationError) {
        setError(messageForError(calculationError));
      }
    },
    [entry, memory, settings.angleMode],
  );

  const reuseHistoryEntry = useCallback((historyEntry: HistoryEntry) => {
    setParts([]);
    setEntry(historyEntry.result);
    setEntryToken(historyEntry.result);
    setEntryStarted(false);
    setEntryIsResult(true);
    setDisplayExpression('');
    setError(null);
    setJustEvaluated(false);
    setRecalledExpression(historyEntry.expression);
    setOpenPanel(null);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && openPanel !== null) {
        event.preventDefault();
        setOpenPanel(null);
        return;
      }
      const target = event.target as HTMLElement | null;
      if (target?.closest('button, input, select, textarea, a')) return;
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
  }, [handleAction, openPanel]);

  const pendingExpression =
    recalledExpression ||
    displayExpression ||
    expressionLabel([
      ...parts,
      ...(entryStarted && parts.length > 0 ? [entryToken] : []),
    ]);
  const shownResult =
    error ??
    (entryIsResult
      ? formatResult(Number(entry), settings)
      : displayNumber(entry, settings.digitGrouping));

  return (
    <>
      <section
        className={`calculator${mode === 'SCI' ? ' calculator--scientific' : ''}`}
        aria-label={`${mode === 'SCI' ? 'Scientific' : 'Standard'} calculator`}
      >
        <div className="calculator__topline">
          <span>OPENCALC / 01</span>
          <span className="calculator__precision">
            {settings.decimalPlaces} decimal places
          </span>
        </div>

        <div className="calculator-toolbar">
          <div className="mode-toggle" role="group" aria-label="Calculator mode">
            {(['STD', 'SCI'] as const).map((calculatorMode) => (
              <button
                type="button"
                key={calculatorMode}
                aria-pressed={mode === calculatorMode}
                onClick={() => setMode(calculatorMode)}
              >
                {calculatorMode}
              </button>
            ))}
          </div>

          {mode === 'SCI' ? (
            <div className="angle-toggle" role="group" aria-label="Angle mode">
              {(['DEG', 'RAD'] as const).map((angleMode) => (
                <button
                  type="button"
                  key={angleMode}
                  aria-pressed={settings.angleMode === angleMode}
                  onClick={() => onSettingsChange({ angleMode })}
                >
                  {angleMode}
                </button>
              ))}
            </div>
          ) : (
            <span className="calculator-toolbar__spacer" />
          )}

          <button
            type="button"
            className="toolbar-button"
            aria-label={`Open history, ${entries.length} entries`}
            onClick={() => setOpenPanel('history')}
          >
            History
            {entries.length > 0 ? (
              <span aria-hidden="true">{entries.length}</span>
            ) : null}
          </button>
          <button
            type="button"
            className="toolbar-button toolbar-button--icon"
            aria-label="Open settings"
            onClick={() => setOpenPanel('settings')}
          >
            ⚙
          </button>
        </div>

        <Display
          expression={pendingExpression}
          result={shownResult}
          isError={error !== null}
          mode={mode}
          angleMode={settings.angleMode}
          hasMemory={memory !== null}
        />

        <div className="memory-keypad" aria-label="Memory controls">
          {(
            [
              ['MC', 'Clear memory', 'clear'],
              ['MR', 'Recall memory', 'recall'],
              ['M+', 'Add display to memory', 'add'],
              ['M−', 'Subtract display from memory', 'subtract'],
              ['MS', 'Store display in memory', 'store'],
            ] as const
          ).map(([visual, label, action]) => (
            <button
              type="button"
              key={action}
              aria-label={label}
              disabled={memory === null && (action === 'clear' || action === 'recall')}
              onClick={() => handleMemory(action)}
            >
              {visual}
            </button>
          ))}
        </div>

        {mode === 'SCI' ? (
          <ScientificKeypad onAction={handleScientificAction} />
        ) : null}

        <Keypad onAction={handleAction} activeKey={activeKey} />
      </section>

      <HistoryPanel
        open={openPanel === 'history'}
        entries={entries}
        privateMode={settings.privateMode}
        onClose={() => setOpenPanel(null)}
        onReuse={reuseHistoryEntry}
        onRemove={removeEntry}
        onClear={clearEntries}
      />
      <SettingsPanel
        open={openPanel === 'settings'}
        settings={settings}
        onClose={() => setOpenPanel(null)}
        onChange={onSettingsChange}
      />
    </>
  );
}
