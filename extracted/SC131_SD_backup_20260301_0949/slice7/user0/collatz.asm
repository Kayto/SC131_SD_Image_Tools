; CP/M-80 2.2 .COM (8080)
; Collatz burn-in: start at 2, then 3, 4, ...
; For each start: compute Collatz in 24-bit, print:
;   N=<start> <steps><CR><LF>
; ESC exits (polled via BDOS 11, read via BDOS 1)
;

        ORG     100H
BDOS    EQU     0005H

START:  LXI     H,2
        SHLD    STNUM

NXST:   ; poll ESC
        CALL    KPOLL
        ORA     A
        JZ      NOKEY
        MVI     C,1
        CALL    BDOS
        CPI     1BH
        JZ      EXIT
NOKEY:

        ; print "N=" + start + " "
        LXI     D,TXTN
        CALL    PSTR
        LHLD    STNUM
        CALL    PDEC
        MVI     A,' '
        CALL    PCH

        ; CURV = STNUM (24-bit LE), STPC = 0
        LHLD    STNUM
        SHLD    CURV
        XRA     A
        STA     CURV+2
        STA     STPC
        STA     STPC+1

STEP:   ; if CURV == 1 => done
        LDA     CURV+2
        ORA     A
        JNZ     NTONE
        LHLD    CURV
        MOV     A,H
        ORA     A
        JNZ     NTONE
        MOV     A,L
        CPI     1
        JZ      DONE

NTONE:  ; odd/even on bit0 of low byte
        LDA     CURV
        ANI     01H
        JNZ     ODD

; -------- EVEN: CURV = CURV / 2 (24-bit shift right) --------
EVEN:   LDA     CURV+2
        ORA     A           ; clear carry
        RAR
        STA     CURV+2
        LDA     CURV+1
        RAR
        STA     CURV+1
        LDA     CURV
        RAR
        STA     CURV
        JMP     SDONE

; -------- ODD: CURV = 3*CURV + 1 (24-bit) --------
ODD:    ; SAVV = CURV
        LHLD    CURV
        SHLD    SAVV
        LDA     CURV+2
        STA     SAVV+2

        ; CURV = 2*CURV (24-bit left shift)
        LHLD    CURV
        DAD     H           ; HL=2x low16, CY carry out
        SHLD    CURV
        LDA     CURV+2
        RAL                 ; bring carry into high byte
        STA     CURV+2

        ; CURV = CURV + SAVV (2x + 1x = 3x)
        LHLD    CURV
        XCHG                ; DE = 2x low16
        LHLD    SAVV        ; HL = orig low16
        DAD     D           ; HL = 3x low16, CY carry
        SHLD    CURV
        LDA     CURV+2      ; 2x high
        MOV     B,A
        LDA     SAVV+2      ; orig high
        ADC     B           ; 3x high = 2x_hi + orig_hi + carry
        STA     CURV+2

        ; +1 (24-bit)
        LHLD    CURV
        INX     H
        SHLD    CURV
        MOV     A,H
        ORA     L
        JNZ     SDONE
        LDA     CURV+2
        INR     A
        STA     CURV+2

; -------- step counter and loop --------
SDONE:  ; STPC++
        LDA     STPC
        INR     A
        STA     STPC
        JNZ     STEP
        LDA     STPC+1
        INR     A
        STA     STPC+1
        JMP     STEP

DONE:   ; print steps then CRLF
        LHLD    STPC
        CALL    PDEC
        CALL    CRLF

        ; next start
        LHLD    STNUM
        INX     H
        SHLD    STNUM
        JMP     NXST

EXIT:   CALL    CRLF
        RET

; =============================================================
; BDOS helpers (preserve regs robustly)
; =============================================================

; Print char in A via BDOS 2, preserving A, BC, DE, HL
PCH:    PUSH    PSW
        PUSH    B
        PUSH    D
        PUSH    H
        MOV     E,A
        MVI     C,2
        CALL    BDOS
        POP     H
        POP     D
        POP     B
        POP     PSW
        RET

; Print $-terminated string at DE via BDOS 9, preserving BC, DE, HL
PSTR:   PUSH    B
        PUSH    D
        PUSH    H
        MVI     C,9
        CALL    BDOS
        POP     H
        POP     D
        POP     B
        RET

CRLF:   MVI     A,0DH
        CALL    PCH
        MVI     A,0AH
        CALL    PCH
        RET

; BDOS 11: console status (A=00 none, FF char ready)
KPOLL:  MVI     C,11
        CALL    BDOS
        RET

; =============================================================
; PDEC: print HL unsigned decimal (0..65535), suppress leading zeros
; Uses B as suppression flag; safe because PCH preserves BC.
; =============================================================
PDEC:   PUSH    B
        PUSH    D
        MVI     B,0
        LXI     D,10000
        CALL    PDIG
        LXI     D,1000
        CALL    PDIG
        LXI     D,100
        CALL    PDIG
        LXI     D,10
        CALL    PDIG
        MOV     A,L
        ADI     '0'
        CALL    PCH
        POP     D
        POP     B
        RET

PDIG:   MVI     C,'0'
PDLP:   MOV     A,L
        SUB     E
        MOV     L,A
        MOV     A,H
        SBB     D
        MOV     H,A
        JC      PDFX
        INR     C
        JMP     PDLP
PDFX:   DAD     D
        MOV     A,C
        CPI     '0'
        JNZ     PDPR
        MOV     A,B
        ORA     A
        RZ                  ; suppress leading zeros
PDPR:   MVI     B,1
        MOV     A,C
        PUSH    H
        CALL    PCH
        POP     H
        RET

; =============================================================
; Data
; =============================================================
TXTN:   DB      'N=','$'

CURV:   DS      3           ; 24-bit current value (LE)
SAVV:   DS      3           ; temp
STNUM:  DS      2           ; current start (16-bit)
STPC:   DS      2           ; step count (16-bit)

        END     START