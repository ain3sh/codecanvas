; =============================================================================
; Definitions
; =============================================================================

(struct_specifier
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(class_specifier
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(function_definition
  declarator: (function_declarator
               declarator: (identifier) @cc.def.func.name)) @cc.def.func.node

(function_definition
  declarator: (function_declarator
               declarator: (field_identifier) @cc.def.func.name)) @cc.def.func.node

(function_definition
  declarator: (function_declarator
               declarator: (qualified_identifier
                            name: (identifier) @cc.def.func.name))) @cc.def.func.node

(function_definition
  declarator: (pointer_declarator
               declarator: (function_declarator
                            declarator: (identifier) @cc.def.func.name))) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(preproc_include
  path: (_) @cc.import.spec)


; =============================================================================
; Calls
; =============================================================================

(call_expression
  function: (identifier) @cc.call.target)

(call_expression
  function: (field_expression
              field: (field_identifier) @cc.call.target))

(call_expression
  function: (qualified_identifier
              name: (identifier) @cc.call.target))
