; =============================================================================
; Definitions
; =============================================================================

(class_definition
  name: (identifier) @cc.def.class.name) @cc.def.class.node

(function_definition
  name: (identifier) @cc.def.func.name) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(import_statement
  (dotted_name) @cc.import.spec)

(import_statement
  (aliased_import
    name: (dotted_name) @cc.import.spec))

(import_from_statement
  module_name: (dotted_name) @cc.import.spec)

(import_from_statement
  module_name: (relative_import) @cc.import.spec)


; =============================================================================
; Calls
; =============================================================================

(call
  function: (identifier) @cc.call.target)

(call
  function: (attribute
              attribute: (identifier) @cc.call.target))
