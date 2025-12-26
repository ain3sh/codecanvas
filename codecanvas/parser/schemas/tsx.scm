; =============================================================================
; Definitions
; =============================================================================

(class_declaration
  name: (type_identifier) @cc.def.class.name) @cc.def.class.node

(function_declaration
  name: (identifier) @cc.def.func.name) @cc.def.func.node

(method_definition
  name: (property_identifier) @cc.def.func.name) @cc.def.func.node

(variable_declarator
  name: (identifier) @cc.def.func.name
  value: [(arrow_function) (function_expression)]) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(import_statement
  source: (string) @cc.import.spec)

(call_expression
  function: (identifier) @cc.import._require
  arguments: (arguments (string) @cc.import.spec)
  (#eq? @cc.import._require "require"))


; =============================================================================
; Calls
; =============================================================================

(call_expression
  function: (identifier) @cc.call.target)

(call_expression
  function: (member_expression
              property: (property_identifier) @cc.call.target))
