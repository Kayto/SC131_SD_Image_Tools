; CP/M-80 2.2 .COM (8080) ? DRI ASM.COM friendly
; 32-bit Collatz explorer (HEX output):
;   N starts at 2 and increments forever (32-bit)
;   Collatz value is 32-bit
; Prints:  N=XXXXXXXX  STEPS=YYYYYYYY
; ESC exits (BDOS 11 poll + BDOS 1 read)
; If odd-step would overflow 32-bit (n > 0x55555554), prints "  OVF" and moves on.
;
; Key robustness change:
;   NO "LABEL+K" addressing anywhere for variables.
;   Every byte has its own label (CUR0..CUR3 etc).

        ORG     100H
BDOS    EQU     0005H

; -------------------------
; Start
; -------------------------
START:  ; STN = 2 (32-bit LE)
        XRA     A
        STA     STN0
        STA     STN1
        STA     STN2
        STA     STN3
        MVI     A,2
        STA     STN0

NXST:   ; poll for ESC
        CALL    KPOLL
        ORA     A
        JZ      NOKEY
        MVI     C,1
        CALL    BDOS
        CPI     1BH
        JZ      EXIT
NOKEY:

        ; Print "N=" + STN (hex) + "  STEPS="
        LXI     D,TXTN
        CALL    PSTR
        LXI     H,STN0
        CALL    PH32
        LXI     D,TXTS
        CALL    PSTR

        ; CUR = STN
        LDA     STN0
        STA     CUR0
        LDA     STN1
        STA     CUR1
        LDA     STN2
        STA     CUR2
        LDA     STN3
        STA     CUR3

        ; STP = 0
        XRA     A
        STA     STP0
        STA     STP1
        STA     STP2
        STA     STP3

STEP:   ; if CUR == 1 then done
        LDA     CUR3
        ORA     A
        JNZ     NTONE
        LDA     CUR2
        ORA     A
        JNZ     NTONE
        LDA     CUR1
        ORA     A
        JNZ     NTONE
        LDA     CUR0
        CPI     1
        JZ      DONE

NTONE:  ; odd/even test
        LDA     CUR0
        ANI     01H
        JNZ     ODD

; ---- EVEN: CUR = CUR / 2 (32-bit shift right)
EVEN:   LDA     CUR3
        ORA     A           ; clear CY
        RAR
        STA     CUR3
        LDA     CUR2
        RAR
        STA     CUR2
        LDA     CUR1
        RAR
        STA     CUR1
        LDA     CUR0
        RAR
        STA     CUR0
        JMP     INCST

; ---- ODD: overflow guard then CUR = 3*CUR + 1
ODD:    CALL    CMPO        ; CY=1 if CUR <= 0x55555554
        JNC     OVF         ; if > max, would overflow on 3n+1

        ; SAV = CUR
        LDA     CUR0
        STA     SAV0
        LDA     CUR1
        STA     SAV1
        LDA     CUR2
        STA     SAV2
        LDA     CUR3
        STA     SAV3

        ; CUR = 2*CUR (32-bit shift left)
        XRA     A           ; clear carry
        LDA     CUR0
        RAL
        STA     CUR0
        LDA     CUR1
        RAL
        STA     CUR1
        LDA     CUR2
        RAL
        STA     CUR2
        LDA     CUR3
        RAL
        STA     CUR3

        ; CUR = CUR + SAV  (=> 3x)
        LDA     CUR0
        ADD     SAV0
        STA     CUR0
        LDA     CUR1
        ADC     SAV1
        STA     CUR1
        LDA     CUR2
        ADC     SAV2
        STA     CUR2
        LDA     CUR3
        ADC     SAV3
        STA     CUR3

        ; +1 (32-bit)
        LDA     CUR0
        INR     A
        STA     CUR0
        JNZ     INCST
        LDA     CUR1
        INR     A
        STA     CUR1
        JNZ     INCST
        LDA     CUR2
        INR     A
        STA     CUR2
        JNZ     INCST
        LDA     CUR3
        INR     A
        STA     CUR3
        JMP     INCST

OVF:    ; print "  OVF" and finish this N
        LXI     D,TXTO
        CALL    PSTR
        CALL    CRLF
        JMP     NXTN

; ---- step counter ++ and loop
INCST:  LDA     STP0
        INR     A
        STA     STP0
        JNZ     STEP
        LDA     STP1
        INR     A
        STA     STP1
        JNZ     STEP
        LDA     STP2
        INR     A
        STA     STP2
        JNZ     STEP
        LDA     STP3
        INR     A
        STA     STP3
        JMP     STEP

DONE:   ; print step count (hex) then CRLF
        LXI     H,STP0
        CALL    PH32
        CALL    CRLF

NXTN:   ; STN++
        CALL    INCN
        JMP     NXST

EXIT:   CALL    CRLF
        RET

; -------------------------
; INCN: increment STN (32-bit)
; -------------------------
INCN:   LDA     STN0
        INR     A
        STA     STN0
        RNZ
        LDA     STN1
        INR     A
        STA     STN1
        RNZ
        LDA     STN2
        INR     A
        STA     STN2
        RNZ
        LDA     STN3
        INR     A
        STA     STN3
        RET

; -------------------------
; CMPO: CY=1 if CUR <= 0x55555554 else CY=0
; (Compare MSB -> LSB)
; -------------------------
CMPO:   LDA     CUR3
        CPI     055H
        JC      CMOK
        JNZ     CMBAD

        LDA     CUR2
        CPI     055H
        JC      CMOK
        JNZ     CMBAD

        LDA     CUR1
        CPI     055H
        JC      CMOK
        JNZ     CMBAD

        LDA     CUR0
        CPI     054H
        JC      CMOK
        JZ      CMOK

CMBAD:  STC                 ; CY=1
        CMC                 ; CY=0
        RET

CMOK:   STC                 ; CY=1
        RET

; -------------------------
; BDOS helpers (preserve regs)
; -------------------------
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

KPOLL:  MVI     C,11
        CALL    BDOS
        RET

; -------------------------
; PH32: print 32-bit value at HL (LE) as 8 hex digits
; (prints MSB first)
; -------------------------
PH32:   PUSH    B
        PUSH    H
        INX     H
        INX     H
        INX     H
        MOV     A,M
        CALL    HX8
        DCX     H
        MOV     A,M
        CALL    HX8
        DCX     H
        MOV     A,M
        CALL    HX8
        DCX     H
        MOV     A,M
        CALL    HX8
        POP     H
        POP     B
        RET

HX8:    PUSH    PSW
        RRC
        RRC
        RRC
        RRC
        ANI     0FH
        CALL    HXN
        POP     PSW
        ANI     0FH
        ; fall through

HXN:    CPI     0AH
        JC      HXD
        ADI     ('A'-0AH)
        JMP     HXO
HXD:    ADI     '0'
HXO:    CALL    PCH
        RET

; -------------------------
; Data
; -------------------------
TXTN:   DB      'N=','$'
TXTS:   DB      '  STEPS=','$'
TXTO:   DB      '  OVF','$'

; 32-bit little-endian variables (explicit byte labels)
STN0:   DS      1
STN1:   DS      1
STN2:   DS      1
STN3:   DS      1

CUR0:   DS      1
CUR1:   DS      1
CUR2:   DS      1
CUR3:   DS      1

SAV0:   DS      1
SAV1:   DS      1
SAV2:   DS      1
SAV3:   DS      1

STP0:   DS      1
STP1:   DS      1
STP2:   DS      1
STP3:   DS      1

        END     START