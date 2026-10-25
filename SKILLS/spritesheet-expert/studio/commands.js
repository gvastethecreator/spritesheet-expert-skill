export function workflowArgv(workflow, values) {
  for (const field of workflow.fields) {
    const value = values[field.id];
    if (field.required && (value === undefined || value === null || String(value).trim() === '')) {
      throw new Error(`${field.label} is required.`);
    }
    if (field.type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) {
      throw new Error(`${field.label} must be a number.`);
    }
    if (field.type === 'select' && !field.options.includes(value)) {
      throw new Error(`Choose a valid ${field.label.toLowerCase()}.`);
    }
    if (typeof value === 'string' && /[\0\r]/.test(value)) {
      throw new Error(`${field.label} cannot contain NUL or carriage returns. Use LF for newlines.`);
    }
  }
  if (workflow.argvTemplate === null) return null;
  return workflow.argvTemplate.map(argument =>
    typeof argument === 'string' ? argument : String(values[argument.field]),
  );
}

export function renderCommand(argv, shell) {
  if (!['posix', 'powershell'].includes(shell)) throw new Error('Choose a supported command shell.');
  if (argv === null) return '# External provider job. Export the JSON handoff for explicit execution.';
  if (!Array.isArray(argv) || !argv.length || argv.some(value => typeof value !== 'string' || /[\0\r]/.test(value))) {
    throw new Error('Command arguments must be strings without NUL or carriage returns.');
  }
  if (shell === 'posix') return argv.map(value => `'${value.replaceAll("'", "'\"'\"'")}'`).join(' ');
  const command = argv.map(value => {
    const lines = value.split('\n').map(line => `'${line.replace(/['\u2018\u2019\u201a\u201b]/g, quote => quote + quote)}'`);
    return lines.length === 1 ? lines[0] : `(${lines.join(' + [char]10 + ')})`;
  }).join(' ');
  return `& {
  if ($PSVersionTable.PSVersion -lt [version]'7.3') { throw 'Use PowerShell 7.3 or newer.' }
  $PSNativeCommandArgumentPassing = 'Standard'
  & ${command}
}`;
}
