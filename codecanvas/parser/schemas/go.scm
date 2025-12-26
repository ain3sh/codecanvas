; =============================================================================
; Definitions
; =============================================================================

(type_spec
  name: (type_identifier) @cc.def.class.name
  type: (struct_type)) @cc.def.class.node

(type_spec
  name: (type_identifier) @cc.def.class.name
  type: (interface_type)) @cc.def.class.node

(function_declaration
  name: (identifier) @cc.def.func.name) @cc.def.func.node

(method_declaration
  name: (field_identifier) @cc.def.func.name) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(import_spec
  path: (interpreted_string_literal) @cc.import.spec)


; =============================================================================
; Calls
; =============================================================================

(call_expression
  function: (identifier) @cc.call.target)

(call_expression
  function: (selector_expression
              field: (field_identifier) @cc.call.target))
