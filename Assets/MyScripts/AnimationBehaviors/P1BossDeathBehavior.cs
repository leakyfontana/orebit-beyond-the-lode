using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class P1BossDeathBehavior : StateMachineBehaviour
{
	public float death_time;
	[HideInInspector]
	public float death_time_left;
	[HideInInspector]
	public Rigidbody2D rb;
	private float height; 
    
    override public void OnStateEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		rb = animator.GetComponent<Rigidbody2D>();
		height = animator.GetComponent<Renderer>().bounds.size.y * 1.5f;
		//rb.position = new Vector2(rb.position.x, rb.position.y - height);
		death_time_left = death_time;
		animator.GetComponent<P1BossMethods>().deactivateCollisions();
		animator.GetComponent<P1BossMethods>().playSound("P1Death");
		animator.GetComponent<P1BossMethods>().startSustainedParticles();
    }
	
	// OnStateUpdate is called on each Update frame between OnStateEnter and OnStateExit callbacks
    override public void OnStateUpdate(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		death_time_left -= Time.deltaTime;
		rb.position = new Vector2(rb.position.x, rb.position.y - ((height * Time.deltaTime)/death_time));
		if(death_time_left <= 0f){
			animator.GetComponent<P1BossMethods>().finishDeath();
		}
    }
	
	override public void OnStateExit(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		animator.GetComponent<P1BossMethods>().reactivateCollisions();
		animator.GetComponent<P1BossMethods>().stopSustainedParticles();
    }
}
