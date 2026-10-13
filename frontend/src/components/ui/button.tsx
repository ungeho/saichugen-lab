import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

const variants = cva('inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40 disabled:cursor-not-allowed', {
  variants: { variant: { default: 'bg-teal-300 text-slate-950 hover:bg-teal-200', outline: 'border border-slate-600 text-slate-100 hover:bg-slate-700' } },
  defaultVariants: { variant: 'default' },
});
export function Button({ className, variant, asChild = false, ...props }: React.ComponentProps<'button'> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : 'button';
  return <Component className={twMerge(clsx(variants({ variant }), className))} {...props} />;
}
