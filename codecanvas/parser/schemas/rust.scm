; =============================================================================
; Definitions
; =============================================================================

(struct_item
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(enum_item
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(trait_item
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(function_item
  name: (identifier) @cc.def.func.name) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(use_declaration
  argument: (_) @cc.import.spec)


; =============================================================================
; Calls
; =============================================================================

(call_expression
  function: (identifier) @cc.call.target)

(call_expression
  function: (field_expression
              field: (field_identifier) @cc.call.target))

(call_expression
  function: (scoped_identifier
              name: (identifier) @cc.call.target))

(macro_invocation
  macro: (identifier) @cc.call.target)
