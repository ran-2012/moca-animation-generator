// Sandbox compatibility shim for running Vite inside the DSH workspace sandbox.
//
// This environment denies Node's `child_process` calls that use piped stdio
// (spawn EPERM). Vite calls `exec("net use")` once, only as an optional probe to
// map Windows network drives; the result is non-essential. Answer it with empty
// output instead of spawning a process. Every other exec call is left untouched.
//
// Invoked via `node --require ./scripts/child-process-shim.cjs <vite>` from the
// npm scripts, so it never leaks into application code.
'use strict'

const cp = require('node:child_process')

if (!cp.__mocadiffShimInstalled) {
  const originalExec = cp.exec

  cp.exec = function exec(cmd, options, callback) {
    const cb = typeof options === 'function' ? options : callback
    if (String(cmd).trim().toLowerCase().startsWith('net use')) {
      if (typeof cb === 'function') process.nextTick(() => cb(null, '', ''))
      const { EventEmitter } = require('node:events')
      const { Readable } = require('node:stream')
      const fake = new EventEmitter()
      fake.stdout = Readable.from([''])
      fake.stderr = Readable.from([''])
      fake.kill = () => fake
      return fake
    }
    return originalExec.apply(cp, arguments)
  }

  cp.__mocadiffShimInstalled = true
}
