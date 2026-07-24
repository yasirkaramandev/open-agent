interface DisplayProps {
  expression: string;
  result: string;
  isError: boolean;
}

export function Display({ expression, result, isError }: DisplayProps) {
  return (
    <div className="display" aria-label="Calculator display">
      <div className="display__status">
        <span className="display__mode">STD</span>
        <span className="display__indicator" aria-label="Calculator is ready">
          READY
        </span>
      </div>

      <div
        className="display__expression"
        aria-label={expression ? `Expression: ${expression}` : 'No expression'}
      >
        {expression || <span aria-hidden="true">0</span>}
      </div>

      <output
        className={`display__result${isError ? ' display__result--error' : ''}`}
        aria-live="polite"
        aria-atomic="true"
        aria-label={isError ? `Error: ${result}` : `Result: ${result}`}
      >
        {result}
      </output>
    </div>
  );
}
