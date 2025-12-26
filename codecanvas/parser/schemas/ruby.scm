; =============================================================================
; Definitions
; =============================================================================

(module
  name: (constant) @cc.def.class.name) @cc.def.class.node

(class
  name: (constant) @cc.def.class.name) @cc.def.class.node

(method
  name: (identifier) @cc.def.func.name) @cc.def.func.node

(singleton_method
  name: (identifier) @cc.def.func.name) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(call
  method: (identifier) @cc.import._method
  arguments: (argument_list (string) @cc.import.spec)
  (#any-of? @cc.import._method "require" "require_relative" "load"))


; =============================================================================
; Calls
; =============================================================================

(call
  method: (identifier) @cc.call.target)
