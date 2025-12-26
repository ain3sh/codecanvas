; =============================================================================
; Definitions
; =============================================================================

(class_declaration
  name: (identifier) @cc.def.class.name) @cc.def.class.node

(interface_declaration
  name: (identifier) @cc.def.class.name) @cc.def.class.node

(enum_declaration
  name: (identifier) @cc.def.class.name) @cc.def.class.node

(method_declaration
  name: (identifier) @cc.def.func.name) @cc.def.func.node

(constructor_declaration
  name: (identifier) @cc.def.func.name) @cc.def.func.node


; =============================================================================
; Imports
; =============================================================================

(import_declaration
  (scoped_identifier) @cc.import.spec)


; =============================================================================
; Calls
; =============================================================================

(method_invocation
  name: (identifier) @cc.call.target)

(object_creation_expression
  type: (type_identifier) @cc.call.target)
