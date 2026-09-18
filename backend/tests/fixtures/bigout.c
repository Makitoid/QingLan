#include <stdio.h>

int main(void) {
    for (long i = 0; i < 12L * 1024 * 1024; i++)
        printf("0123456789\n");
    return 0;
}
