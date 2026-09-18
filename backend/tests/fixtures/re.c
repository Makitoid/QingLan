#include <stdio.h>

int main(void) {
    volatile int *p = (volatile int *)0;
    printf("%d\n", *p);
    return 0;
}
