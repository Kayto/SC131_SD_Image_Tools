ORG 100H

START:
    MVI  A,20H          ; FIRST PRINTABLE

PRINTLOOP:
    PUSH PSW            ; SAVE A+FLAGS (LOOP COUNTER)
    MOV  E,A            ; CHAR -> E
    MVI  C,2            ; BDOS CONSOLE OUTPUT
    CALL 5
    POP  PSW            ; RESTORE A

    INR  A
    CPI  80H
    JNZ  PRINTLOOP

    ; NEWLINE (OPTIONAL BUT HELPS VISIBILITY ON SOME TERMINALS)
    MVI  E,0DH
    MVI  C,2
    CALL 5
    MVI  E,0AH
    MVI  C,2
    CALL 5

    ; WAIT FOR KEY
    MVI  C,1
    CALL 5
    RET

END START