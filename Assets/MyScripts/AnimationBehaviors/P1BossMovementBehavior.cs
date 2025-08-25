using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class BossMovement : StateMachineBehaviour
{
	Rigidbody2D rb;
	Transform player;
	public float speed;
	float target_x;
    // OnStateEnter is called when a transition starts and the state machine starts to evaluate this state
    override public void OnStateEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
        player = GameObject.FindGameObjectWithTag("Player").transform;
		rb = animator.GetComponent<Rigidbody2D>();
    }

    // OnStateUpdate is called on each Update frame between OnStateEnter and OnStateExit callbacks
    override public void OnStateUpdate(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		if(animator.GetComponent<P1BossMethods>().is_facing_left){
			target_x = 0.5f;
		}
		else {
			target_x = 35.5f;
		}
		if(Vector2.Distance(rb.position, new Vector2(target_x, rb.position.y)) <= 0.1f){
			animator.GetComponent<P1BossMethods>().flipBoss();
		}
        Vector2 target = new Vector2(target_x, rb.position.y);
		Vector2 new_pos = Vector2.MoveTowards(rb.position, target, speed * Time.deltaTime);
		rb.MovePosition(new_pos);
    }

    // OnStateExit is called when a transition ends and the state machine finishes evaluating this state
    //override public void OnStateExit(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    //{
    //    
    //}

    // OnStateMove is called right after Animator.OnAnimatorMove()
    //override public void OnStateMove(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    //{
    //    // Implement code that processes and affects root motion
    //}

    // OnStateIK is called right after Animator.OnAnimatorIK()
    //override public void OnStateIK(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    //{
    //    // Implement code that sets up animation IK (inverse kinematics)
    //}
}
